"""GL-related endpoints: /api/gl-spend and /api/items-per-gl."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, text
from app.database import get_session
from app.auth import get_current_user, property_scope
from app.models import GLSpendItem, ItemsPerGLEntry, GLLineItemDetail
from app.table_models import User

router = APIRouter(prefix="/api")


@router.get("/gl-spend", response_model=list[GLSpendItem])
def gl_spend(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Total spend and item count grouped by AI-assigned GL code, sorted by spend descending."""
    pc = property_scope(current_user)
    inv_join = "JOIN invoices inv ON inv.id = li.invoice_id" if pc else ""
    pc_filter = "AND inv.property_code = :pc" if pc else ""
    params = {"pc": pc} if pc else {}

    rows = session.execute(text(f"""
        SELECT
            li.assigned_gl_code                                 AS gl_code,
            COALESCE(li.assigned_gl_desc, gc.sdesc, 'Unknown') AS gl_desc,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)            AS total_spend,
            COUNT(*)                                            AS item_count
        FROM line_items li
        LEFT JOIN gl_codes gc ON gc.scode = li.assigned_gl_code
        {inv_join}
        WHERE li.assigned_gl_code IS NOT NULL
          AND li.needs_review = 0
          {pc_filter}
        GROUP BY li.assigned_gl_code
        ORDER BY total_spend DESC
    """), params).mappings().all()

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
def items_per_gl(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Item count and spend per GL code, with the individual line items nested."""
    pc = property_scope(current_user)
    inv_join = "JOIN invoices inv ON inv.id = li.invoice_id" if pc else ""
    pc_filter = "AND inv.property_code = :pc" if pc else ""
    params = {"pc": pc} if pc else {}

    summary_rows = session.execute(text(f"""
        SELECT
            li.assigned_gl_code                                  AS gl_code,
            COALESCE(li.assigned_gl_desc, gc.sdesc, 'Unknown')  AS gl_desc,
            COUNT(*)                                             AS item_count,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)             AS total_spend
        FROM line_items li
        LEFT JOIN gl_codes gc ON gc.scode = li.assigned_gl_code
        {inv_join}
        WHERE li.assigned_gl_code IS NOT NULL
          AND li.needs_review = 0
          {pc_filter}
        GROUP BY li.assigned_gl_code
        ORDER BY item_count DESC
    """), params).mappings().all()

    if not summary_rows:
        return []

    # Detail rows always join invoices (needed for property_code display + filter)
    detail_filter = "AND inv.property_code = :pc" if pc else ""
    detail_rows = session.execute(text(f"""
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
          {detail_filter}
        ORDER BY li.assigned_gl_code, li.id
    """), params).mappings().all()

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
