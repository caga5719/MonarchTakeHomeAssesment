"""
AI classification service.

For every unclassified line item, calls Claude (Haiku) to assign the best-fit
GL code from the purchasing-relevant subset of the GL chart, or flags it for
human review if no code is a confident match.

Usage:
    uv run python app/classify.py            # classify all unclassified items
    uv run python app/classify.py --validate # run post-classification checks only
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from database import get_connection

# Load ANTHROPIC_API_KEY from backend/.env
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")

# ---------------------------------------------------------------------------
# GL code filtering
# ---------------------------------------------------------------------------

EXCLUDE_PATTERNS = [
    "TOTAL", "NET ",           # roll-up rows
    "WAGES", "PAYROLL", "BONUS", "WORKMANS COMP",
    "HEALTH INSURANCE", "401(K)", "EMPLOYER TAX",  # payroll
    "INVESTMENT", "INTEREST EXPENSE", "MORTGAGE",  # financing
    "DO NOT USE",              # deprecated
]

EXCLUDE_SCODE_RANGES = [
    (5000, 5999),   # income accounts
    (6600, 6665),   # utilities
    (7290, 7320),   # interest/mortgage
]


def load_purchasing_gl_codes(conn) -> list[dict]:
    """Return GL codes relevant to purchasing, excluding roll-ups, payroll, etc."""
    rows = conn.execute(
        "SELECT scode, sdesc FROM gl_codes ORDER BY scode"
    ).fetchall()
    result = []
    for row in rows:
        scode, sdesc = row["scode"], row["sdesc"]
        if sdesc is None:
            continue
        if any(p in sdesc.upper() for p in EXCLUDE_PATTERNS):
            continue
        if any(lo <= scode <= hi for lo, hi in EXCLUDE_SCODE_RANGES):
            continue
        result.append({"scode": scode, "sdesc": sdesc})
    return result


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(
    invoice_gl: int | None,
    invoice_gl_desc: str | None,
    line_items: list[dict],
    gl_codes: list[dict],
) -> str:
    gl_list = "\n".join(f"{g['scode']}: {g['sdesc']}" for g in gl_codes)

    if invoice_gl and invoice_gl_desc:
        hint = f"GL {invoice_gl} ({invoice_gl_desc})"
    elif invoice_gl:
        hint = f"GL {invoice_gl}"
    else:
        hint = "unknown"

    items_text = "\n".join(
        f"{i+1}. [ID {item['id']}] {item['description']} "
        f"(qty: {item['quantity']}, unit price: ${item['unit_price']})"
        for i, item in enumerate(line_items)
    )

    return f"""You are a property management accounting assistant.

The invoice was coded at the header level as {hint}.
Use this as a hint, but classify each line item independently based on its description.

GL chart (purchasing-relevant codes only):
{gl_list}

Classify each line item. Return a JSON array — one object per item, in any order:
[{{"id": <line_item_id>, "gl_code": <scode or null>, "note": "<one sentence reason>"}}]

IMPORTANT: If no code is a reasonable fit for a line item, return gl_code: null
and explain why in the note. Do not guess — a null with a reason is more useful
than a plausible-sounding wrong code.

Line items:
{items_text}"""


# ---------------------------------------------------------------------------
# Per-invoice classification
# ---------------------------------------------------------------------------

def classify_invoice(invoice_id: int, conn, client: anthropic.Anthropic) -> dict:
    """
    Classify all unclassified, non-discount line items for one invoice.

    Returns a dict with counts: {classified, needs_review, skipped}.
    """
    # Fetch invoice-level GL for context hint
    invoice_row = conn.execute(
        """
        SELECT i.invoice_gl_code, g.sdesc
        FROM invoices i
        LEFT JOIN gl_codes g ON g.scode = i.invoice_gl_code
        WHERE i.id = ?
        """,
        (invoice_id,),
    ).fetchone()

    invoice_gl = invoice_row["invoice_gl_code"] if invoice_row else None
    invoice_gl_desc = invoice_row["sdesc"] if invoice_row else None

    # Fetch unclassified, non-discount items (quantity IS NOT NULL = not a promo row)
    items = conn.execute(
        """
        SELECT id, description, quantity, unit_price
        FROM line_items
        WHERE invoice_id = ?
          AND assigned_gl_code IS NULL
          AND needs_review = 0
          AND quantity IS NOT NULL
        """,
        (invoice_id,),
    ).fetchall()

    if not items:
        return {"classified": 0, "needs_review": 0, "skipped": 0}

    items_list = [dict(row) for row in items]

    # Fetch purchasing GL codes (same for every invoice — caller could cache this,
    # but for simplicity we load it once per invoice call; the set is ~140 rows)
    gl_codes = load_purchasing_gl_codes(conn)

    prompt = build_prompt(invoice_gl, invoice_gl_desc, items_list, gl_codes)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()

    # Extract JSON array from response (Claude sometimes wraps it in markdown)
    json_start = raw_text.find("[")
    json_end = raw_text.rfind("]") + 1
    if json_start == -1 or json_end == 0:
        raise ValueError(f"No JSON array found in response: {raw_text[:200]}")

    classifications = json.loads(raw_text[json_start:json_end])

    # Build a lookup by id for O(1) access
    gl_lookup = {g["scode"]: g["sdesc"] for g in gl_codes}
    classified = 0
    needs_review = 0

    with conn:
        for entry in classifications:
            item_id = entry.get("id")
            gl_code = entry.get("gl_code")
            note = entry.get("note", "")

            if gl_code is not None:
                gl_code = int(gl_code)
                gl_desc = gl_lookup.get(gl_code)
                conn.execute(
                    """
                    UPDATE line_items
                    SET assigned_gl_code = ?,
                        assigned_gl_desc = ?,
                        classification_note = ?,
                        needs_review = 0
                    WHERE id = ?
                    """,
                    (gl_code, gl_desc, note, item_id),
                )
                classified += 1
            else:
                conn.execute(
                    """
                    UPDATE line_items
                    SET assigned_gl_code = NULL,
                        assigned_gl_desc = NULL,
                        classification_note = ?,
                        needs_review = 1
                    WHERE id = ?
                    """,
                    (note, item_id),
                )
                needs_review += 1

    skipped = len(items_list) - classified - needs_review
    return {"classified": classified, "needs_review": needs_review, "skipped": skipped}


# ---------------------------------------------------------------------------
# Batch entry point
# ---------------------------------------------------------------------------

def classify_all(conn, client: anthropic.Anthropic) -> None:
    """Classify all invoices that have at least one unclassified line item."""
    invoice_ids = conn.execute(
        """
        SELECT DISTINCT invoice_id
        FROM line_items
        WHERE assigned_gl_code IS NULL
          AND needs_review = 0
          AND quantity IS NOT NULL
        ORDER BY invoice_id
        """
    ).fetchall()

    total_invoices = len(invoice_ids)
    if total_invoices == 0:
        print("No unclassified line items found — nothing to do.")
        return

    print(f"Classifying {total_invoices} invoice(s)…", flush=True)

    total_classified = 0
    total_needs_review = 0
    errors = []

    for i, row in enumerate(invoice_ids, 1):
        invoice_id = row["invoice_id"]
        try:
            counts = classify_invoice(invoice_id, conn, client)
            total_classified += counts["classified"]
            total_needs_review += counts["needs_review"]
            print(
                f"  [{i}/{total_invoices}] invoice_id={invoice_id} "
                f"classified={counts['classified']} "
                f"needs_review={counts['needs_review']} "
                f"(running total: {total_classified} classified, {total_needs_review} flagged)",
                flush=True,
            )
        except Exception as exc:
            errors.append((invoice_id, str(exc)))
            print(f"  [{i}/{total_invoices}] invoice_id={invoice_id} ERROR: {exc}", flush=True)

    print(
        f"\nDone. Classified {total_classified} item(s), "
        f"{total_needs_review} flagged for review."
    )
    if errors:
        print(f"\n{len(errors)} invoice(s) failed:")
        for inv_id, msg in errors:
            print(f"  invoice_id={inv_id}: {msg}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(conn) -> None:
    """Print post-classification quality checks."""
    # Every classifiable item must have a code or be flagged
    missed = conn.execute(
        """
        SELECT COUNT(*) as n
        FROM line_items
        WHERE assigned_gl_code IS NULL
          AND needs_review = 0
          AND quantity IS NOT NULL
        """
    ).fetchone()["n"]

    review_count = conn.execute(
        "SELECT COUNT(*) as n FROM line_items WHERE needs_review = 1"
    ).fetchone()["n"]

    print(f"Unclassified items (should be 0): {missed}")
    print(f"Items flagged needs_review:        {review_count}")

    print("\n--- 10 random classified items ---")
    samples = conn.execute(
        """
        SELECT description, assigned_gl_code, assigned_gl_desc, classification_note
        FROM line_items
        WHERE assigned_gl_code IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 10
        """
    ).fetchall()
    for s in samples:
        print(
            f"  [{s['assigned_gl_code']}] {s['assigned_gl_desc']}\n"
            f"    item: {s['description'][:70]}\n"
            f"    note: {s['classification_note']}\n"
        )

    print("--- needs_review items (all) ---")
    review_items = conn.execute(
        """
        SELECT li.id, li.description, li.classification_note,
               i.invoice_number
        FROM line_items li
        JOIN invoices i ON i.id = li.invoice_id
        WHERE li.needs_review = 1
        """
    ).fetchall()
    for r in review_items:
        print(
            f"  id={r['id']} invoice={r['invoice_number']}\n"
            f"    item: {r['description'][:70]}\n"
            f"    note: {r['classification_note']}\n"
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify invoice line items with Claude")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run post-classification checks only (no API calls)",
    )
    args = parser.parse_args()

    conn = get_connection()

    if args.validate:
        validate(conn)
        conn.close()
        sys.exit(0)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to backend/.env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    classify_all(conn, client)
    conn.close()

    print("\nRunning validation…")
    conn2 = get_connection()
    validate(conn2)
    conn2.close()
