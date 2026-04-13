"""Invoice endpoints: /api/invoices (paginated) and /api/invoices/{invoice_number}."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.database import get_connection
from app.models import InvoiceListItem, InvoiceDetail, LineItemDetail, PaginatedInvoices

router = APIRouter(prefix="/api")


def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("/invoices", response_model=PaginatedInvoices)
def list_invoices(
    property: Optional[str] = Query(None, description="Filter by property code (case-insensitive)"),
    gl: Optional[int] = Query(None, description="Filter by invoice-level GL code"),
    search: Optional[str] = Query(None, description="Search invoice number, property code, or purchaser"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db=Depends(get_db),
):
    """Paginated list of invoices with optional filters."""
    conditions = []
    params: list = []

    if property:
        conditions.append("UPPER(inv.property_code) = UPPER(?)")
        params.append(property)
    if gl is not None:
        conditions.append("inv.invoice_gl_code = ?")
        params.append(gl)
    if search:
        like = f"%{search}%"
        conditions.append(
            "(inv.invoice_number LIKE ? OR UPPER(inv.property_code) LIKE UPPER(?) OR inv.purchaser LIKE ?)"
        )
        params.extend([like, like, like])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total_row = db.execute(
        f"SELECT COUNT(*) AS cnt FROM invoices inv {where}", params
    ).fetchone()
    total = total_row["cnt"]

    offset = (page - 1) * page_size
    rows = db.execute(
        f"""
        SELECT
            inv.id,
            inv.invoice_number,
            inv.property_code,
            inv.invoice_gl_code,
            gc.sdesc              AS invoice_gl_desc,
            inv.invoice_date,
            inv.purchaser,
            ROUND(inv.total_amount, 2) AS total_amount,
            inv.needs_review
        FROM invoices inv
        LEFT JOIN gl_codes gc ON gc.scode = inv.invoice_gl_code
        {where}
        ORDER BY inv.invoice_date DESC, inv.id DESC
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    items = [
        InvoiceListItem(
            id=r["id"],
            invoice_number=r["invoice_number"],
            property_code=r["property_code"],
            invoice_gl_code=r["invoice_gl_code"],
            invoice_gl_desc=r["invoice_gl_desc"],
            invoice_date=r["invoice_date"],
            purchaser=r["purchaser"],
            total_amount=r["total_amount"],
            needs_review=bool(r["needs_review"]),
        )
        for r in rows
    ]

    return PaginatedInvoices(items=items, total=total, page=page, page_size=page_size)


@router.get("/invoices/{invoice_number}", response_model=InvoiceDetail)
def get_invoice(invoice_number: str, db=Depends(get_db)):
    """Full invoice record with classified line items."""
    inv = db.execute(
        """
        SELECT
            inv.*,
            gc.sdesc AS invoice_gl_desc
        FROM invoices inv
        LEFT JOIN gl_codes gc ON gc.scode = inv.invoice_gl_code
        WHERE inv.invoice_number = ?
        """,
        [invoice_number],
    ).fetchone()

    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_number}' not found")

    li_rows = db.execute(
        """
        SELECT *
        FROM line_items
        WHERE invoice_id = ?
        ORDER BY line_number
        """,
        [inv["id"]],
    ).fetchall()

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
