"""
PDF ingestion pipeline.

Parses every invoice PDF in Invoices/ and writes structured records to the
invoices and line_items tables.

Usage:
    uv run python app/ingest.py           # ingest all PDFs
    uv run python app/ingest.py --dry-run # print parsed data, don't write to DB
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

from database import get_connection, init_db

REPO_ROOT = Path(__file__).resolve().parents[2]
INVOICES_DIR = REPO_ROOT / "Invoices"

# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

# Strips the repeated page-continuation header that appears when an invoice
# spans multiple pages:
#   Page1 of 2
#   Invoice
#   Invoice # XXXX-XXXX-XXXX
#   Item subtotal
#   Description Qty Unit price before tax Tax
_PAGE_BREAK_RE = re.compile(
    r"\nPage\d+ of \d+\nInvoice\nInvoice # [\w-]+\n"
    r"Item subtotal\nDescription Qty Unit price before tax Tax\n"
)

# Strips the trailing FAQ page (page 2 or last page of every invoice)
_FAQ_RE = re.compile(r"\nFAQs\b.*", re.DOTALL)


def _clean_text(full_text: str) -> str:
    """Remove page-break artifacts and trailing FAQ section."""
    text = _PAGE_BREAK_RE.sub("\n", full_text)
    text = _FAQ_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Header field extraction
# ---------------------------------------------------------------------------

def _re_find(pattern: str, text: str, group: int = 1, flags: int = 0):
    """Return the first capture group or None."""
    m = re.search(pattern, text, flags)
    return m.group(group) if m else None


def _parse_date(s: str | None, fmt: str) -> str | None:
    """Parse a date string and return ISO format, or None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), fmt).date().isoformat()
    except ValueError:
        return None


def _parse_amount(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _parse_header(text: str) -> dict:
    """Extract invoice-level fields from the text."""

    # Invoice number
    invoice_number = _re_find(r"Invoice # ([\w-]+)", text)

    # Invoice date — from the "Invoice # XXXX | Month DD, YYYY" line
    inv_date_str = _re_find(r"Invoice # [\w-]+ \| (.+)", text)
    invoice_date = _parse_date(inv_date_str, "%B %d, %Y")

    # Due date — "Payment due by Month DD, YYYY"
    due_date_str = _re_find(r"Payment due by (.+?) Account", text)
    due_date = _parse_date(due_date_str, "%B %d, %Y")

    # Purchase date — "Purchase date DD-Mon-YYYY" (e.g. 26-Mar-2026)
    purchase_date_str = _re_find(r"Purchase date\s+([\d]+-[A-Za-z]+-[\d]+)", text)
    purchase_date = _parse_date(purchase_date_str, "%d-%b-%Y")

    # Use invoice_date as fallback for invoice_date field; purchase_date is
    # the actual transaction date — store it as invoice_date in the DB.
    effective_date = purchase_date or invoice_date

    # Purchaser
    purchaser = _re_find(r"Purchased by\s+(.+)", text)

    # PO number
    po_number = _re_find(r"PO #\s+(\d+)", text)

    # GL code (may not be present on all invoices)
    gl_code_str = _re_find(r"GL code\s+(\d+)", text)
    invoice_gl_code = int(gl_code_str) if gl_code_str else None

    # Property code — normalize to UPPERCASE; may contain slashes (e.g. BPAL/CHAL)
    property_code_raw = _re_find(r"Property Code\s+(\S+)", text)
    property_code = property_code_raw.upper() if property_code_raw else None

    # Financial totals
    # "Item subtotal before tax $X" appears in the summary header
    subtotal = _parse_amount(_re_find(r"Item subtotal before tax\s+\$([\d,.]+)", text))
    # "Tax $ X.XX" — note possible space before the amount
    tax = _parse_amount(_re_find(r"(?m)^Tax\s+\$\s*([\d,.]+)", text))
    # "Amount due $X.XX USD"
    total_amount = _parse_amount(_re_find(r"Amount due\s+\$([\d,.]+)", text))

    return {
        "invoice_number": invoice_number,
        "invoice_date": effective_date,
        "due_date": due_date,
        "purchaser": purchaser,
        "po_number": po_number,
        "invoice_gl_code": invoice_gl_code,
        "property_code": property_code,
        "subtotal": subtotal,
        "tax": tax,
        "total_amount": total_amount,
    }


# ---------------------------------------------------------------------------
# Line item extraction
# ---------------------------------------------------------------------------

# Matches the trailing qty / unit-price / subtotal / tax fields on an item's
# first line:  ...description... 2 $5.99 $11.98 8.000%
_ITEM_LINE_RE = re.compile(
    r"^(\d+)\s+"               # line number
    r"(.+?)\s+"                # description (greedy up to price block)
    r"(\d+(?:\.\d+)?)\s+"      # qty
    r"\$([\d,]+(?:\.\d+)?)\s+" # unit price
    r"\$([\d,]+(?:\.\d+)?)\s+" # subtotal before tax
    r"([\d.]+)%$",             # tax rate
    re.MULTILINE,
)

# Discount / promo row: "N Promotions & discounts ($X.XX) Y%"
_DISCOUNT_LINE_RE = re.compile(
    r"^\d+\s+Promotions\s*&\s*discounts",
    re.IGNORECASE | re.MULTILINE,
)

# ASIN is always B followed by 9 uppercase alphanumeric chars (10 total)
_ASIN_RE = re.compile(r"\b(B[A-Z0-9]{9})\b")


def _extract_item_blocks(items_section: str) -> list[str]:
    """
    Split the items section into per-item text blocks.

    Uses the full first-line price pattern to identify true item starts, which
    avoids treating part-number continuation lines (e.g. "341474 469474") as
    new items.
    """
    lines = items_section.split("\n")
    item_start_indices = []

    for i, line in enumerate(lines):
        if _ITEM_LINE_RE.match(line) or _DISCOUNT_LINE_RE.match(line):
            item_start_indices.append(i)

    if not item_start_indices:
        return []

    blocks = []
    for idx, start in enumerate(item_start_indices):
        end = item_start_indices[idx + 1] if idx + 1 < len(item_start_indices) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        blocks.append(block)

    return blocks


def _parse_item_block(block: str, line_number_hint: int | None = None) -> dict | None:
    """
    Parse a single item block into a dict.
    Returns None if the block is a discount/promo row.
    """
    # Skip discount rows
    if _DISCOUNT_LINE_RE.match(block):
        return None

    lines = block.split("\n")
    first_line = lines[0]

    m = _ITEM_LINE_RE.match(first_line)
    if not m:
        # Could not parse price info from first line — skip silently
        return None

    line_number = int(m.group(1))
    desc_start = m.group(2).strip()
    qty = float(m.group(3))
    unit_price = _parse_amount(m.group(4))
    subtotal = _parse_amount(m.group(5))
    tax_rate = float(m.group(6))

    # Collect description continuation lines (before ASIN / Sold by / Order #)
    desc_extra_lines = []
    for line in lines[1:]:
        if re.match(r"^(ASIN:|Sold by:|Order #|Page\d+)", line, re.IGNORECASE):
            break
        if line.strip():
            desc_extra_lines.append(line.strip())

    description = " ".join([desc_start] + desc_extra_lines).strip()

    # ASIN — search entire block
    asin_m = _ASIN_RE.search(block)
    asin = asin_m.group(1) if asin_m else None

    return {
        "line_number": line_number,
        "description": description,
        "asin": asin,
        "quantity": qty,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "tax_rate": tax_rate,
    }


def _extract_line_items(text: str) -> list[dict]:
    """Extract all line items from the cleaned invoice text."""
    # Isolate the items section: after the column header, before totals
    header_m = re.search(r"Description\s+Qty\s+Unit price\s+before tax\s+Tax\n", text)
    if not header_m:
        return []

    items_section = text[header_m.end():]

    # Truncate at the summary totals block
    totals_m = re.search(r"\nTotal before tax\s+\$", items_section)
    if totals_m:
        items_section = items_section[: totals_m.start()]

    blocks = _extract_item_blocks(items_section)
    items = []
    for block in blocks:
        item = _parse_item_block(block)
        if item is not None:
            items.append(item)

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_invoice(pdf_path: Path) -> dict:
    """
    Parse a single invoice PDF.

    Returns:
        {
            "header": { invoice_number, property_code, ... },
            "line_items": [ { line_number, description, ... }, ... ]
        }
    """
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]

    full_text = "\n".join(pages_text)
    clean = _clean_text(full_text)

    header = _parse_header(clean)
    header["filename"] = pdf_path.name

    line_items = _extract_line_items(clean)

    return {"header": header, "line_items": line_items}


def ingest_all(invoices_dir: Path, dry_run: bool = False) -> None:
    """
    Iterate all PDFs in invoices_dir, parse each one, and write to the DB.
    Invoices already in the DB (by invoice_number) are skipped.
    """
    if not dry_run:
        init_db()

    pdfs = sorted(invoices_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {invoices_dir}")
        return

    total_invoices = 0
    total_line_items = 0
    total_needs_review = 0
    skipped = 0
    errors = []

    conn = None if dry_run else get_connection()

    try:
        for pdf_path in pdfs:
            try:
                result = parse_invoice(pdf_path)
            except Exception as exc:
                errors.append((pdf_path.name, str(exc)))
                continue

            header = result["header"]
            items = result["line_items"]
            inv_num = header.get("invoice_number")

            if not inv_num:
                errors.append((pdf_path.name, "Could not parse invoice number"))
                continue

            if not dry_run:
                # Skip if already ingested
                existing = conn.execute(
                    "SELECT id FROM invoices WHERE invoice_number = ?", (inv_num,)
                ).fetchone()
                if existing:
                    skipped += 1
                    continue

            if dry_run:
                _print_dry_run(pdf_path.name, header, items)
                total_line_items += len(items)
            else:
                flagged = _write_to_db(conn, header, items)
                if flagged:
                    total_needs_review += 1
                else:
                    total_line_items += len(items)

            total_invoices += 1

    finally:
        if conn:
            conn.close()

    print(
        f"\nProcessed {total_invoices} invoice(s), "
        f"{total_line_items} line item(s), "
        f"{skipped} skipped (already in DB)"
    )
    if total_needs_review:
        print(f"{total_needs_review} invoice(s) flagged needs_review (unknown property code)")
    if errors:
        print(f"\n{len(errors)} error(s):")
        for name, msg in errors:
            print(f"  {name}: {msg}")


def _write_to_db(conn, header: dict, items: list[dict]) -> bool:
    """
    Insert invoice header and line items in a single transaction.

    Returns True if the invoice was flagged needs_review (unknown property code),
    in which case no line items are written.
    """
    property_code = header["property_code"]

    # Check whether the property code exists in the reference table
    needs_review = 0
    if property_code:
        row = conn.execute(
            "SELECT 1 FROM properties WHERE yardi_code = ?", (property_code,)
        ).fetchone()
        if row is None:
            needs_review = 1
    else:
        needs_review = 1  # no property code at all

    with conn:
        cursor = conn.execute(
            """
            INSERT INTO invoices
                (invoice_number, property_code, invoice_gl_code, invoice_date,
                 due_date, purchaser, po_number, subtotal, tax, total_amount,
                 filename, needs_review)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                header["invoice_number"],
                property_code,
                header["invoice_gl_code"],
                header["invoice_date"],
                header["due_date"],
                header["purchaser"],
                header["po_number"],
                header["subtotal"],
                header["tax"],
                header["total_amount"],
                header["filename"],
                needs_review,
            ),
        )
        invoice_id = cursor.lastrowid

        if not needs_review:
            conn.executemany(
                """
                INSERT INTO line_items
                    (invoice_id, line_number, description, asin, quantity,
                     unit_price, subtotal, tax_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        invoice_id,
                        item["line_number"],
                        item["description"],
                        item["asin"],
                        item["quantity"],
                        item["unit_price"],
                        item["subtotal"],
                        item["tax_rate"],
                    )
                    for item in items
                ],
            )

    return bool(needs_review)


def _print_dry_run(filename: str, header: dict, items: list[dict]) -> None:
    print(f"\n{'='*60}")
    print(f"File    : {filename}")
    print(f"Invoice : {header['invoice_number']}")
    print(f"Property: {header['property_code']}")
    print(f"GL code : {header['invoice_gl_code']}")
    print(f"Date    : {header['invoice_date']}")
    print(f"Total   : {header['total_amount']}")
    print(f"Items   : {len(items)}")
    for item in items:
        print(
            f"  [{item['line_number']}] qty={item['quantity']} "
            f"${item['unit_price']} | {item['description'][:60]}"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Amazon invoice PDFs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parsed data without writing to DB",
    )
    parser.add_argument(
        "--invoices-dir",
        type=Path,
        default=INVOICES_DIR,
        help="Directory containing invoice PDFs",
    )
    args = parser.parse_args()

    ingest_all(args.invoices_dir, dry_run=args.dry_run)
