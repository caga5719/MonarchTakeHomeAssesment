"""Property-related endpoints: /api/items-per-property."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, text
from app.database import get_session
from app.auth import get_current_user
from app.models import ItemsPerPropertyEntry
from app.table_models import User

router = APIRouter(prefix="/api")


@router.get("/items-per-property", response_model=list[ItemsPerPropertyEntry])
def items_per_property(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Line-item count, total spend, and invoice count per property code.

    Admin-only — non-admin users receive 403.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This view is only available to admin users",
        )

    rows = session.execute(text("""
        SELECT
            inv.property_code,
            COUNT(li.id)                              AS item_count,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)  AS total_spend,
            COUNT(DISTINCT li.invoice_id)             AS invoice_count
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        WHERE inv.property_code IS NOT NULL
          AND inv.processed = 1
        GROUP BY inv.property_code
        ORDER BY total_spend DESC
    """)).mappings().all()

    return [
        ItemsPerPropertyEntry(
            property_code=r["property_code"],
            item_count=r["item_count"],
            total_spend=r["total_spend"],
            invoice_count=r["invoice_count"],
        )
        for r in rows
    ]
