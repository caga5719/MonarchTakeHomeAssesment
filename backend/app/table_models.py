"""
SQLModel table definitions — single source of truth for the database schema.

These replace schema.sql. init_db() calls SQLModel.metadata.create_all() to
create tables that don't yet exist; existing tables and data are left intact.
"""

from typing import Optional
from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class GLCode(SQLModel, table=True):
    __tablename__ = "gl_codes"

    scode: int = Field(primary_key=True)
    sdesc: str


class Property(SQLModel, table=True):
    __tablename__ = "properties"

    yardi_code: str = Field(primary_key=True)   # uppercase; matches property_code on invoices
    website_id: Optional[str] = None
    name: Optional[str] = None
    state: Optional[str] = None
    unit_count: Optional[int] = None


class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_property_code", "property_code"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_number: str = Field(unique=True)
    property_code: Optional[str] = None          # soft ref to properties.yardi_code (uppercase)
    invoice_gl_code: Optional[int] = None         # header-level GL
    invoice_date: Optional[str] = None            # stored as ISO date string
    due_date: Optional[str] = None
    purchaser: Optional[str] = None
    po_number: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total_amount: Optional[float] = None
    filename: str
    needs_review: int = 0                         # 1 when property_code not in properties table
    processed: int = 0                            # 1 when Claude has classified all line items


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    hashed_password: str
    name: str
    role: Optional[str] = None            # 'admin' | 'manager' | 'operations'
    property_code: Optional[str] = None   # soft ref to properties.yardi_code (uppercase)


class LineItem(SQLModel, table=True):
    __tablename__ = "line_items"
    __table_args__ = (
        Index("idx_line_items_invoice_id", "invoice_id"),
        Index("idx_line_items_assigned_gl", "assigned_gl_code"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: Optional[int] = Field(default=None, foreign_key="invoices.id")
    line_number: Optional[int] = None
    description: str
    asin: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    subtotal: Optional[float] = None
    tax_rate: Optional[float] = None
    # AI-assigned classification (may differ from invoice-level GL)
    assigned_gl_code: Optional[int] = None
    assigned_gl_desc: Optional[str] = None
    classification_note: Optional[str] = None
    needs_review: int = 0                         # 1 when Claude returned null (no confident GL match)
