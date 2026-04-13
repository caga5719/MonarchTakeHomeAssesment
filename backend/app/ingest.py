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
from sqlmodel import Session, select

import table_models  # noqa: F401 — registers SQLModel tables with metadata
from database import engine, init_db
from table_models import Invoice, LineItem, Property

REPO_ROOT = Path(__file__).resolve().parents[2]
INVOICES_DIR = REPO_ROOT / "Invoices"

# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

_PAGE_BREAK_RE = re.compile(
    r"\nPage\d+ of \d+\nInvoice\nInvoice # [\w-]+\n"
    r"Item subtotal\nDescription Qty Unit price before tax Tax\n"
)
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
    m = re.search(pattern, text, flags)
    return m.group(group) if m else None


def _parse_date(s: str | None, fmt: str) -> str | None:
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
    invoice_number = _re_find(r"Invoice # ([\w-]+)", text)
    inv_date_str = _re_find(r"Invoice # [\w-]+ \| (.+)", text)
    invoice_date = _parse_date(inv_date_str, "%B %d, %Y")
    due_date_str = _re_find(r"Payment due by (.+?) Account", text)
    due_date = _parse_date(due_date_str, "%B %d, %Y")
    purchase_date_str = _re_find(r"Purchase date\s+([\d]+-[A-Za-z]+-[\d]+)", text)
    purchase_date = _parse_date(purchase_date_str, "%d-%b-%Y")
    effective_date = purchase_date or invoice_date
    purchaser = _re_find(r"Purchased by\s+(.+)", text)
    po_number = _re_find(r"PO #\s+(\d+)", text)
    gl_code_str = _re_find(r"GL code\s+(\d+)", text)
    invoice_gl_code = int(gl_code_str) if gl_code_str else None
    property_code_raw = _re_find(r"Property Code\s+(\S+)", text)
    property_code = property_code_raw.upper() if property_code_raw else None
    subtotal = _parse_amount(_re_find(r"Item subtotal before tax\s+\$([\d,.]+)", text))
    tax = _parse_amount(_re_find(r"(?m)^Tax\s+\$\s*([\d,.]+)", text))
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

_ITEM_LINE_RE = re.compile(
    r"^(\d+)\s+"
    r"(.+?)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"\$([\d,]+(?:\.\d+)?)\s+"
    r"\$([\d,]+(?:\.\d+)?)\s+"
    r"([\d.]+)%$",
    re.MULTILINE,
)
_DISCOUNT_LINE_RE = re.compile(r"^\d+\s+Promotions\s*&\s*discounts", re.IGNORECASE | re.MULTILINE)
_ASIN_RE = re.compile(r"\b(B[A-Z0-9]{9})\b")


def _extract_item_blocks(items_section: str) -> list[str]:
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
        blocks.append("\n".join(lines[start:end]).strip())
    return blocks


def _parse_item_block(block: str) -> dict | None:
    if _DISCOUNT_LINE_RE.match(block):
        return None
    lines = block.split("\n")
    m = _ITEM_LINE_RE.match(lines[0])
    if not m:
        return None
    line_number = int(m.group(1))
    desc_start = m.group(2).strip()
    qty = float(m.group(3))
    unit_price = _parse_amount(m.group(4))
    subtotal = _parse_amount(m.group(5))
    tax_rate = float(m.group(6))
    desc_extra_lines = []
    for line in lines[1:]:
        if re.match(r"^(ASIN:|Sold by:|Order #|Page\d+)", line, re.IGNORECASE):
            break
        if line.strip():
            desc_extra_lines.append(line.strip())
    description = " ".join([desc_start] + desc_extra_lines).strip()
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
    header_m = re.search(r"Description\s+Qty\s+Unit price\s+before tax\s+Tax\n", text)
    if not header_m:
        return []
    items_section = text[header_m.end():]
    totals_m = re.search(r"\nTotal before tax\s+\$", items_section)
    if totals_m:
        items_section = items_section[: totals_m.start()]
    blocks = _extract_item_blocks(items_section)
    return [item for block in blocks if (item := _parse_item_block(block)) is not None]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_invoice(pdf_path: Path) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n".join(pages_text)
    clean = _clean_text(full_text)
    header = _parse_header(clean)
    header["filename"] = pdf_path.name
    return {"header": header, "line_items": _extract_line_items(clean)}


def ingest_all(invoices_dir: Path, dry_run: bool = False) -> None:
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

    if dry_run:
        for pdf_path in pdfs:
            try:
                result = parse_invoice(pdf_path)
            except Exception as exc:
                errors.append((pdf_path.name, str(exc)))
                continue
            header = result["header"]
            if not header.get("invoice_number"):
                errors.append((pdf_path.name, "Could not parse invoice number"))
                continue
            _print_dry_run(pdf_path.name, header, result["line_items"])
            total_line_items += len(result["line_items"])
            total_invoices += 1
    else:
        with Session(engine) as session:
            for pdf_path in pdfs:
                try:
                    result = parse_invoice(pdf_path)
                except Exception as exc:
                    errors.append((pdf_path.name, str(exc)))
                    continue

                header = result["header"]
                inv_num = header.get("invoice_number")
                if not inv_num:
                    errors.append((pdf_path.name, "Could not parse invoice number"))
                    continue

                existing = session.exec(
                    select(Invoice).where(Invoice.invoice_number == inv_num)
                ).first()
                if existing:
                    skipped += 1
                    continue

                flagged = _write_to_db(session, header, result["line_items"])
                if flagged:
                    total_needs_review += 1
                else:
                    total_line_items += len(result["line_items"])
                total_invoices += 1

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


def _write_to_db(session: Session, header: dict, items: list[dict]) -> bool:
    """
    Insert invoice header and line items in a single transaction.
    Returns True if the invoice was flagged needs_review (unknown property code).
    """
    property_code = header["property_code"]

    needs_review = 0
    if property_code:
        prop = session.exec(
            select(Property).where(Property.yardi_code == property_code)
        ).first()
        if prop is None:
            needs_review = 1
    else:
        needs_review = 1

    invoice = Invoice(
        invoice_number=header["invoice_number"],
        property_code=property_code,
        invoice_gl_code=header["invoice_gl_code"],
        invoice_date=header["invoice_date"],
        due_date=header["due_date"],
        purchaser=header["purchaser"],
        po_number=header["po_number"],
        subtotal=header["subtotal"],
        tax=header["tax"],
        total_amount=header["total_amount"],
        filename=header["filename"],
        needs_review=needs_review,
    )
    session.add(invoice)
    session.flush()  # populate invoice.id before inserting line items

    if not needs_review:
        for item in items:
            session.add(LineItem(
                invoice_id=invoice.id,
                line_number=item["line_number"],
                description=item["description"],
                asin=item["asin"],
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                subtotal=item["subtotal"],
                tax_rate=item["tax_rate"],
            ))

    session.commit()
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
    parser.add_argument("--dry-run", action="store_true", help="Print parsed data without writing to DB")
    parser.add_argument("--invoices-dir", type=Path, default=INVOICES_DIR)
    args = parser.parse_args()
    ingest_all(args.invoices_dir, dry_run=args.dry_run)
