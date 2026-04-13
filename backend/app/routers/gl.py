"""GL-related endpoints: /api/gl-spend and /api/items-per-gl."""

from fastapi import APIRouter, Depends
from app.database import get_connection
from app.models import GLSpendItem, ItemsPerGLEntry, GLLineItemDetail

router = APIRouter(prefix="/api")


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/gl-spend", response_model=list[GLSpendItem])
def gl_spend(db=Depends(get_db)):
    """Total spend and item count grouped by AI-assigned GL code, sorted by spend descending."""
    rows = db.execute("""
        SELECT
            li.assigned_gl_code                         AS gl_code,
            COALESCE(li.assigned_gl_desc, gc.sdesc, 'Unknown')  AS gl_desc,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)    AS total_spend,
            COUNT(*)                                    AS item_count
        FROM line_items li
        LEFT JOIN gl_codes gc ON gc.scode = li.assigned_gl_code
        WHERE li.assigned_gl_code IS NOT NULL
          AND li.needs_review = 0
        GROUP BY li.assigned_gl_code
        ORDER BY total_spend DESC
    """).fetchall()

    return [
        GLSpendItem(
            gl_code=r["gl_code"],
            gl_desc=r["gl_desc"],
            total_spend=r["total_spend"],
            item_count=r["item_count"],
        )
        for r in rows
    ]


@router.get("/items-per-gl", response_model=list[ItemsPerGLEntry])
def items_per_gl(db=Depends(get_db)):
    """Item count and spend per GL code, with the individual line items nested."""
    # Aggregate per GL
    summary_rows = db.execute("""
        SELECT
            li.assigned_gl_code                                  AS gl_code,
            COALESCE(li.assigned_gl_desc, gc.sdesc, 'Unknown')  AS gl_desc,
            COUNT(*)                                             AS item_count,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)             AS total_spend
        FROM line_items li
        LEFT JOIN gl_codes gc ON gc.scode = li.assigned_gl_code
        WHERE li.assigned_gl_code IS NOT NULL
          AND li.needs_review = 0
        GROUP BY li.assigned_gl_code
        ORDER BY item_count DESC
    """).fetchall()

    if not summary_rows:
        return []

    # Fetch all detail rows in one query, then group in Python
    detail_rows = db.execute("""
        SELECT
            inv.invoice_number,
            inv.property_code,
            li.description,
            ROUND(COALESCE(li.subtotal, 0), 2) AS subtotal,
            li.assigned_gl_code
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        WHERE li.assigned_gl_code IS NOT NULL
          AND li.needs_review = 0
        ORDER BY li.assigned_gl_code, li.id
    """).fetchall()

    # Group details by gl_code
    from collections import defaultdict
    details: dict[int, list[GLLineItemDetail]] = defaultdict(list)
    for d in detail_rows:
        details[d["assigned_gl_code"]].append(
            GLLineItemDetail(
                invoice_number=d["invoice_number"],
                property_code=d["property_code"],
                description=d["description"],
                subtotal=d["subtotal"],
            )
        )

    return [
        ItemsPerGLEntry(
            gl_code=r["gl_code"],
            gl_desc=r["gl_desc"],
            item_count=r["item_count"],
            total_spend=r["total_spend"],
            items=details.get(r["gl_code"], []),
        )
        for r in summary_rows
    ]
