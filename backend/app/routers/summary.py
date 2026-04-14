"""Summary, mismatch, and needs-review endpoints."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, text
from app.database import get_session
from app.auth import get_current_user, property_scope
from app.models import SummaryResponse, TopGL, TopProperty, MismatchItem, NeedsReviewItem
from app.table_models import User

router = APIRouter(prefix="/api")


@router.get("/summary", response_model=SummaryResponse)
def summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """High-level dashboard numbers, scoped to the authenticated user's property."""
    pc = property_scope(current_user)

    # Build join/filter fragments used across all queries
    # li_join: appended when querying line_items without an existing invoices join
    # inv_filter: WHERE clause addition for any query that already has invoices
    li_join = "JOIN invoices inv ON inv.id = li.invoice_id" if pc else ""
    inv_filter = "AND inv.property_code = :pc" if pc else ""
    params: dict = {"pc": pc} if pc else {}

    total_invoices = session.execute(
        text(f"""
            SELECT COUNT(*) AS c FROM invoices
            WHERE processed = 1
            {'AND property_code = :pc' if pc else ''}
        """),
        params,
    ).mappings().first()["c"]

    total_spend = session.execute(text(f"""
        SELECT ROUND(COALESCE(SUM(li.subtotal), 0), 2) AS s
        FROM line_items li
        {li_join}
        WHERE li.assigned_gl_code IS NOT NULL AND li.needs_review = 0
        {inv_filter}
    """), params).mappings().first()["s"]

    total_line_items = session.execute(text(f"""
        SELECT COUNT(*) AS c FROM line_items li
        {li_join}
        WHERE (li.assigned_gl_code IS NOT NULL OR li.needs_review = 1)
        {inv_filter}
    """), params).mappings().first()["c"]

    if pc:
        properties_count = 1
    else:
        properties_count = session.execute(text(
            "SELECT COUNT(DISTINCT property_code) AS c FROM invoices WHERE property_code IS NOT NULL"
        )).mappings().first()["c"]

    needs_review_count = session.execute(text(f"""
        SELECT COUNT(*) AS c FROM line_items li
        {li_join}
        WHERE li.needs_review = 1
        {inv_filter}
    """), params).mappings().first()["c"]

    top_gl_row = session.execute(text(f"""
        SELECT
            li.assigned_gl_code                                  AS gl_code,
            COALESCE(li.assigned_gl_desc, gc.sdesc, 'Unknown')  AS gl_desc,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2)             AS total_spend
        FROM line_items li
        LEFT JOIN gl_codes gc ON gc.scode = li.assigned_gl_code
        {li_join}
        WHERE li.assigned_gl_code IS NOT NULL AND li.needs_review = 0
        {inv_filter}
        GROUP BY li.assigned_gl_code
        ORDER BY total_spend DESC
        LIMIT 1
    """), params).mappings().first()

    top_property_row = session.execute(text(f"""
        SELECT
            inv.property_code,
            ROUND(SUM(COALESCE(li.subtotal, 0)), 2) AS total_spend
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        WHERE inv.property_code IS NOT NULL
        {inv_filter}
        GROUP BY inv.property_code
        ORDER BY total_spend DESC
        LIMIT 1
    """), params).mappings().first()

    return SummaryResponse(
        total_invoices=total_invoices,
        total_spend=total_spend,
        total_line_items=total_line_items,
        properties_count=properties_count,
        top_gl=TopGL(
            gl_code=top_gl_row["gl_code"],
            gl_desc=top_gl_row["gl_desc"],
            total_spend=top_gl_row["total_spend"],
        ) if top_gl_row else None,
        top_property=TopProperty(
            property_code=top_property_row["property_code"],
            total_spend=top_property_row["total_spend"],
        ) if top_property_row else None,
        needs_review_count=needs_review_count,
    )


@router.get("/mismatches", response_model=list[MismatchItem])
def mismatches(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Line items where the AI-assigned GL differs from the invoice-level GL."""
    pc = property_scope(current_user)
    pc_filter = "AND inv.property_code = :pc" if pc else ""
    params: dict = {"pc": pc} if pc else {}

    rows = session.execute(text(f"""
        SELECT
            inv.invoice_number,
            inv.property_code,
            inv.invoice_gl_code,
            igc.sdesc                                   AS invoice_gl_desc,
            li.description                              AS line_item_desc,
            li.assigned_gl_code,
            COALESCE(li.assigned_gl_desc, agc.sdesc)   AS assigned_gl_desc,
            ROUND(COALESCE(li.subtotal, 0), 2)         AS subtotal
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        LEFT JOIN gl_codes igc ON igc.scode = inv.invoice_gl_code
        LEFT JOIN gl_codes agc ON agc.scode = li.assigned_gl_code
        WHERE li.needs_review = 0
          AND li.assigned_gl_code IS NOT NULL
          AND li.assigned_gl_code != inv.invoice_gl_code
          {pc_filter}
        ORDER BY inv.invoice_number, li.line_number
    """), params).mappings().all()

    return [
        MismatchItem(
            invoice_number=r["invoice_number"],
            property_code=r["property_code"],
            invoice_gl_code=r["invoice_gl_code"],
            invoice_gl_desc=r["invoice_gl_desc"],
            line_item_desc=r["line_item_desc"],
            assigned_gl_code=r["assigned_gl_code"],
            assigned_gl_desc=r["assigned_gl_desc"],
            subtotal=r["subtotal"],
        )
        for r in rows
    ]


@router.get("/needs-review", response_model=list[NeedsReviewItem])
def needs_review(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Line items where Claude could not assign a confident GL code."""
    pc = property_scope(current_user)
    pc_filter = "AND inv.property_code = :pc" if pc else ""
    params: dict = {"pc": pc} if pc else {}

    rows = session.execute(text(f"""
        SELECT
            li.id,
            inv.invoice_number,
            inv.property_code,
            li.description,
            li.classification_note,
            inv.invoice_gl_code,
            gc.sdesc AS invoice_gl_desc
        FROM line_items li
        JOIN invoices inv ON inv.id = li.invoice_id
        LEFT JOIN gl_codes gc ON gc.scode = inv.invoice_gl_code
        WHERE li.needs_review = 1
        {pc_filter}
        ORDER BY inv.invoice_number, li.line_number
    """), params).mappings().all()

    return [
        NeedsReviewItem(
            id=r["id"],
            invoice_number=r["invoice_number"],
            property_code=r["property_code"],
            description=r["description"],
            classification_note=r["classification_note"],
            invoice_gl_code=r["invoice_gl_code"],
            invoice_gl_desc=r["invoice_gl_desc"],
        )
        for r in rows
    ]
