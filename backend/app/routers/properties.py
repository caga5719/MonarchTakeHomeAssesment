"""Property-related endpoints: /api/items-per-property."""

from fastapi import APIRouter, Depends
from app.database import get_connection
from app.models import ItemsPerPropertyEntry

router = APIRouter(prefix="/api")


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/items-per-property", response_model=list[ItemsPerPropertyEntry])
def items_per_property(db=Depends(get_db)):
    """Line-item count, total spend, and invoice count per property code, sorted by spend descending."""
    rows = db.execute("""
        SELECT
            inv.property_code,
            COUNT(li.id)                              AS item_count,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)  AS total_spend,
            COUNT(DISTINCT li.invoice_id)             AS invoice_count
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        WHERE inv.property_code IS NOT NULL
        GROUP BY inv.property_code
        ORDER BY total_spend DESC
    """).fetchall()

    return [
        ItemsPerPropertyEntry(
            property_code=r["property_code"],
            item_count=r["item_count"],
            total_spend=r["total_spend"],
            invoice_count=r["invoice_count"],
        )
        for r in rows
    ]
