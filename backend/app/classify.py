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
from sqlmodel import Session, select, text

import table_models  # noqa: F401 — registers SQLModel tables with metadata
from database import engine
from table_models import GLCode, Invoice, LineItem

# Load ANTHROPIC_API_KEY from backend/.env
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")

# ---------------------------------------------------------------------------
# GL code filtering
# ---------------------------------------------------------------------------

EXCLUDE_PATTERNS = [
    "TOTAL", "NET ",
    "WAGES", "PAYROLL", "BONUS", "WORKMANS COMP",
    "HEALTH INSURANCE", "401(K)", "EMPLOYER TAX",
    "INVESTMENT", "INTEREST EXPENSE", "MORTGAGE",
    "DO NOT USE",
]

EXCLUDE_SCODE_RANGES = [
    (5000, 5999),
    (6600, 6665),
    (7290, 7320),
]


def load_purchasing_gl_codes(session: Session) -> list[dict]:
    """Return GL codes relevant to purchasing, excluding roll-ups, payroll, etc."""
    rows = session.exec(select(GLCode).order_by(GLCode.scode)).all()
    result = []
    for row in rows:
        if row.sdesc is None:
            continue
        if any(p in row.sdesc.upper() for p in EXCLUDE_PATTERNS):
            continue
        if any(lo <= row.scode <= hi for lo, hi in EXCLUDE_SCODE_RANGES):
            continue
        result.append({"scode": row.scode, "sdesc": row.sdesc})
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

def classify_invoice(invoice_id: int, session: Session, client: anthropic.Anthropic) -> dict:
    """
    Classify all unclassified, non-discount line items for one invoice.
    Returns a dict with counts: {classified, needs_review, skipped}.
    """
    inv_row = session.execute(text("""
        SELECT i.invoice_gl_code, g.sdesc
        FROM invoices i
        LEFT JOIN gl_codes g ON g.scode = i.invoice_gl_code
        WHERE i.id = :invoice_id
    """), {"invoice_id": invoice_id}).mappings().first()

    invoice_gl = inv_row["invoice_gl_code"] if inv_row else None
    invoice_gl_desc = inv_row["sdesc"] if inv_row else None

    items = session.execute(text("""
        SELECT id, description, quantity, unit_price
        FROM line_items
        WHERE invoice_id = :invoice_id
          AND assigned_gl_code IS NULL
          AND needs_review = 0
          AND quantity IS NOT NULL
    """), {"invoice_id": invoice_id}).mappings().all()

    if not items:
        return {"classified": 0, "needs_review": 0, "skipped": 0}

    items_list = [dict(row) for row in items]
    gl_codes = load_purchasing_gl_codes(session)
    prompt = build_prompt(invoice_gl, invoice_gl_desc, items_list, gl_codes)

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    json_start = raw_text.find("[")
    json_end = raw_text.rfind("]") + 1
    if json_start == -1 or json_end == 0:
        raise ValueError(f"No JSON array found in response: {raw_text[:200]}")

    classifications = json.loads(raw_text[json_start:json_end])
    gl_lookup = {g["scode"]: g["sdesc"] for g in gl_codes}
    classified = 0
    needs_review = 0

    for entry in classifications:
        item_id = entry.get("id")
        gl_code = entry.get("gl_code")
        note = entry.get("note", "")

        if gl_code is not None:
            gl_code = int(gl_code)
            gl_desc = gl_lookup.get(gl_code)
            session.execute(text("""
                UPDATE line_items
                SET assigned_gl_code = :gl_code,
                    assigned_gl_desc = :gl_desc,
                    classification_note = :note,
                    needs_review = 0
                WHERE id = :item_id
            """), {"gl_code": gl_code, "gl_desc": gl_desc, "note": note, "item_id": item_id})
            classified += 1
        else:
            session.execute(text("""
                UPDATE line_items
                SET assigned_gl_code = NULL,
                    assigned_gl_desc = NULL,
                    classification_note = :note,
                    needs_review = 1
                WHERE id = :item_id
            """), {"note": note, "item_id": item_id})
            needs_review += 1

    session.commit()

    # Mark invoice as processed so reruns skip it
    session.execute(
        text("UPDATE invoices SET processed = 1 WHERE id = :invoice_id"),
        {"invoice_id": invoice_id},
    )
    session.commit()

    skipped = len(items_list) - classified - needs_review
    return {"classified": classified, "needs_review": needs_review, "skipped": skipped}


# ---------------------------------------------------------------------------
# Batch entry point
# ---------------------------------------------------------------------------

def classify_all(session: Session, client: anthropic.Anthropic) -> None:
    """Classify all invoices not yet processed by Claude."""
    invoice_ids = session.execute(text("""
        SELECT id AS invoice_id
        FROM invoices
        WHERE processed = 0
          AND needs_review = 0
        ORDER BY id
    """)).mappings().all()

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
            counts = classify_invoice(invoice_id, session, client)
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

    print(f"\nDone. Classified {total_classified} item(s), {total_needs_review} flagged for review.")
    if errors:
        print(f"\n{len(errors)} invoice(s) failed:")
        for inv_id, msg in errors:
            print(f"  invoice_id={inv_id}: {msg}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(session: Session) -> None:
    """Print post-classification quality checks."""
    missed = session.execute(text("""
        SELECT COUNT(*) as n
        FROM line_items
        WHERE assigned_gl_code IS NULL
          AND needs_review = 0
          AND quantity IS NOT NULL
    """)).mappings().first()["n"]

    review_count = session.execute(
        text("SELECT COUNT(*) as n FROM line_items WHERE needs_review = 1")
    ).mappings().first()["n"]

    print(f"Unclassified items (should be 0): {missed}")
    print(f"Items flagged needs_review:        {review_count}")

    print("\n--- 10 random classified items ---")
    samples = session.execute(text("""
        SELECT description, assigned_gl_code, assigned_gl_desc, classification_note
        FROM line_items
        WHERE assigned_gl_code IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 10
    """)).mappings().all()
    for s in samples:
        print(
            f"  [{s['assigned_gl_code']}] {s['assigned_gl_desc']}\n"
            f"    item: {s['description'][:70]}\n"
            f"    note: {s['classification_note']}\n"
        )

    print("--- needs_review items (all) ---")
    review_items = session.execute(text("""
        SELECT li.id, li.description, li.classification_note, i.invoice_number
        FROM line_items li
        JOIN invoices i ON i.id = li.invoice_id
        WHERE li.needs_review = 1
    """)).mappings().all()
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
    parser.add_argument("--validate", action="store_true", help="Run post-classification checks only (no API calls)")
    args = parser.parse_args()

    with Session(engine) as session:
        if args.validate:
            validate(session)
            sys.exit(0)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY not set. Add it to backend/.env")
            sys.exit(1)

        client = anthropic.Anthropic(api_key=api_key)
        classify_all(session, client)

        print("\nRunning validation…")
        validate(session)
