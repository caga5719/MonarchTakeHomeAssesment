"""Invoice endpoints: /api/invoices (paginated) and /api/invoices/{invoice_number}."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, text
from app.database import get_session
from app.auth import get_current_user, property_scope
from app.models import InvoiceListItem, InvoiceDetail, LineItemDetail, PaginatedInvoices
from app.table_models import User

router = APIRouter(prefix="/api")


@router.get("/invoices", response_model=PaginatedInvoices)
def list_invoices(
    property: Optional[str] = Query(None, description="Filter by property code (admin only; non-admin always sees their own property)"),
    gl: Optional[int] = Query(None, description="Filter by invoice-level GL code"),
    line_item_gl: Optional[int] = Query(None, description="Filter to invoices containing at least one line item with this assigned GL code"),
    search: Optional[str] = Query(None, description="Search invoice number, property code, or purchaser"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Paginated list of invoices with optional filters.

    Non-admin users are automatically scoped to their assigned property_code;
    any ?property= param they pass is ignored.
    """
    pc = property_scope(current_user)

    conditions = ["inv.processed = 1"]
    params: dict = {}

    if pc:
        # Non-admin: always restrict to their property (ignore ?property= param)
        conditions.append("UPPER(inv.property_code) = :pc")
        params["pc"] = pc
    elif property:
        # Admin with explicit property filter
        conditions.append("UPPER(inv.property_code) = UPPER(:property_filter)")
        params["property_filter"] = property

    if gl is not None:
        conditions.append("inv.invoice_gl_code = :gl_filter")
        params["gl_filter"] = gl
    if line_item_gl is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM line_items li WHERE li.invoice_id = inv.id AND li.assigned_gl_code = :line_item_gl)"
        )
        params["line_item_gl"] = line_item_gl
    if search:
        like = f"%{search}%"
        conditions.append(
            "(inv.invoice_number LIKE :s1 OR UPPER(inv.property_code) LIKE UPPER(:s2) OR inv.purchaser LIKE :s3)"
        )
        params.update({"s1": like, "s2": like, "s3": like})

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = session.execute(
        text(f"SELECT COUNT(*) AS cnt FROM invoices inv {where}"), params
    ).mappings().first()["cnt"]

    rows = session.execute(
        text(f"""
        SELECT
            inv.id,
            inv.invoice_number,
            inv.property_code,
            inv.invoice_gl_code,
            gc.sdesc              AS invoice_gl_desc,
            inv.invoice_date,
            inv.purchaser,
            ROUND(inv.subtotal, 2) AS subtotal,
            ROUND(inv.tax, 2)      AS tax,
            inv.needs_review
        FROM invoices inv
        LEFT JOIN gl_codes gc ON gc.scode = inv.invoice_gl_code
        {where}
        ORDER BY inv.invoice_date DESC, inv.id DESC
        LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()

    items = [
        InvoiceListItem(
            id=r["id"],
            invoice_number=r["invoice_number"],
            property_code=r["property_code"],
            invoice_gl_code=r["invoice_gl_code"],
            invoice_gl_desc=r["invoice_gl_desc"],
            invoice_date=r["invoice_date"],
            purchaser=r["purchaser"],
            subtotal=r["subtotal"],
            tax=r["tax"],
            needs_review=bool(r["needs_review"]),
        )
        for r in rows
    ]

    return PaginatedInvoices(items=items, total=total, page=page, page_size=page_size)


@router.get("/invoices/{invoice_number}", response_model=InvoiceDetail)
def get_invoice(
    invoice_number: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Full invoice record with classified line items.

    Non-admin users can only retrieve invoices belonging to their property.
    """
    inv = session.execute(
        text("""
        SELECT
            inv.*,
            gc.sdesc AS invoice_gl_desc
        FROM invoices inv
        LEFT JOIN gl_codes gc ON gc.scode = inv.invoice_gl_code
        WHERE inv.invoice_number = :invoice_number
        """),
        {"invoice_number": invoice_number},
    ).mappings().first()

    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_number}' not found")

    # Enforce property scope for non-admin users
    pc = property_scope(current_user)
    if pc and (inv["property_code"] is None or inv["property_code"].upper() != pc):
        raise HTTPException(status_code=403, detail="Access denied")

    li_rows = session.execute(
        text("""
        SELECT
            id, invoice_id, line_number, description, asin, quantity,
            ROUND(unit_price, 2) AS unit_price,
            ROUND(subtotal, 2)   AS subtotal,
            tax_rate, assigned_gl_code, assigned_gl_desc,
            classification_note, needs_review
        FROM line_items
        WHERE invoice_id = :inv_id
        ORDER BY line_number
        """),
        {"inv_id": inv["id"]},
    ).mappings().all()

    line_items = [
        LineItemDetail(
            id=r["id"],
            line_number=r["line_number"],
            description=r["description"],
            asin=r["asin"],
            quantity=r["quantity"],
            unit_price=round(r["unit_price"], 2) if r["unit_price"] is not None else None,
            subtotal=round(r["subtotal"], 2) if r["subtotal"] is not None else None,
            tax_rate=r["tax_rate"],
            assigned_gl_code=r["assigned_gl_code"],
            assigned_gl_desc=r["assigned_gl_desc"],
            classification_note=r["classification_note"],
            needs_review=bool(r["needs_review"]),
        )
        for r in li_rows
    ]

    return InvoiceDetail(
        id=inv["id"],
        invoice_number=inv["invoice_number"],
        property_code=inv["property_code"],
        invoice_gl_code=inv["invoice_gl_code"],
        invoice_gl_desc=inv["invoice_gl_desc"],
        invoice_date=inv["invoice_date"],
        due_date=inv["due_date"],
        purchaser=inv["purchaser"],
        po_number=inv["po_number"],
        subtotal=round(inv["subtotal"], 2) if inv["subtotal"] is not None else None,
        tax=round(inv["tax"], 2) if inv["tax"] is not None else None,
        total_amount=round(inv["total_amount"], 2) if inv["total_amount"] is not None else None,
        filename=inv["filename"],
        needs_review=bool(inv["needs_review"]),
        line_items=line_items,
    )
