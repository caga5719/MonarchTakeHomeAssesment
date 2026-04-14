"""Pydantic response models for all API endpoints."""

from typing import Optional
from sqlmodel import SQLModel as BaseModel


# ── /api/auth/token ───────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str


# ── /api/auth/register  /api/users/me ────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    role: Optional[str] = None            # 'admin' | 'manager' | 'operations'
    property_code: Optional[str] = None


class UserResponse(BaseModel):
    id: Optional[int]
    username: str
    name: str
    role: Optional[str]
    property_code: Optional[str]


# ── /api/summary ─────────────────────────────────────────────────────────────

class TopGL(BaseModel):
    gl_code: int
    gl_desc: str
    total_spend: float

class TopProperty(BaseModel):
    property_code: str
    total_spend: float

class SummaryResponse(BaseModel):
    total_invoices: int
    total_spend: float
    total_line_items: int
    properties_count: int
    top_gl: Optional[TopGL]
    top_property: Optional[TopProperty]
    needs_review_count: int


# ── /api/gl-spend ─────────────────────────────────────────────────────────────

class GLSpendItem(BaseModel):
    gl_code: int
    gl_desc: str
    total_spend: float
    item_count: int


# ── /api/items-per-gl ─────────────────────────────────────────────────────────

class GLLineItemDetail(BaseModel):
    invoice_number: str
    property_code: Optional[str]
    description: str
    subtotal: Optional[float]

class ItemsPerGLEntry(BaseModel):
    gl_code: int
    gl_desc: str
    item_count: int
    total_spend: float
    items: list[GLLineItemDetail]


# ── /api/items-per-property ───────────────────────────────────────────────────

class ItemsPerPropertyEntry(BaseModel):
    property_code: str
    item_count: int
    total_spend: float
    invoice_count: int


# ── /api/invoices (paginated list) ────────────────────────────────────────────

class InvoiceListItem(BaseModel):
    id: int
    invoice_number: str
    property_code: Optional[str]
    invoice_gl_code: Optional[int]
    invoice_gl_desc: Optional[str]
    invoice_date: Optional[str]
    purchaser: Optional[str]
    subtotal: Optional[float]
    tax: Optional[float]
    needs_review: bool

class PaginatedInvoices(BaseModel):
    items: list[InvoiceListItem]
    total: int
    page: int
    page_size: int


# ── /api/invoices/{invoice_number} ────────────────────────────────────────────

class LineItemDetail(BaseModel):
    id: int
    line_number: Optional[int]
    description: str
    asin: Optional[str]
    quantity: Optional[float]
    unit_price: Optional[float]
    subtotal: Optional[float]
    tax_rate: Optional[float]
    assigned_gl_code: Optional[int]
    assigned_gl_desc: Optional[str]
    classification_note: Optional[str]
    needs_review: bool

class InvoiceDetail(BaseModel):
    id: int
    invoice_number: str
    property_code: Optional[str]
    invoice_gl_code: Optional[int]
    invoice_gl_desc: Optional[str]
    invoice_date: Optional[str]
    due_date: Optional[str]
    purchaser: Optional[str]
    po_number: Optional[str]
    subtotal: Optional[float]
    tax: Optional[float]
    total_amount: Optional[float]
    filename: str
    needs_review: bool
    line_items: list[LineItemDetail]


# ── /api/mismatches ───────────────────────────────────────────────────────────

class MismatchItem(BaseModel):
    invoice_number: str
    property_code: Optional[str]
    invoice_gl_code: Optional[int]
    invoice_gl_desc: Optional[str]
    line_item_desc: str
    assigned_gl_code: int
    assigned_gl_desc: Optional[str]
    subtotal: Optional[float]


# ── /api/needs-review ─────────────────────────────────────────────────────────

class NeedsReviewItem(BaseModel):
    id: int
    invoice_number: str
    property_code: Optional[str]
    description: str
    classification_note: Optional[str]
    invoice_gl_code: Optional[int]
    invoice_gl_desc: Optional[str]
