-- Reference tables (seeded at startup from xlsx files)

CREATE TABLE IF NOT EXISTS gl_codes (
    scode   INTEGER PRIMARY KEY,
    sdesc   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS properties (
    yardi_code  TEXT PRIMARY KEY,   -- uppercase; matches property_code on invoices
    website_id  TEXT,
    name        TEXT,
    state       TEXT,
    unit_count  INTEGER
);

-- Invoice data

CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number  TEXT UNIQUE NOT NULL,
    property_code   TEXT,                               -- soft ref to properties.yardi_code (uppercase)
    invoice_gl_code INTEGER,                            -- header-level GL (soft ref to gl_codes.scode)
    invoice_date    TEXT,                               -- stored as ISO date string
    due_date        TEXT,
    purchaser       TEXT,
    po_number       TEXT,
    subtotal        REAL,
    tax             REAL,
    total_amount    REAL,
    filename        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id          INTEGER REFERENCES invoices(id),
    line_number         INTEGER,
    description         TEXT NOT NULL,
    asin                TEXT,
    quantity            REAL,
    unit_price          REAL,
    subtotal            REAL,
    tax_rate            REAL,
    -- AI-assigned classification (may differ from invoice-level GL)
    assigned_gl_code    INTEGER,                        -- soft ref to gl_codes.scode
    assigned_gl_desc    TEXT,
    classification_note TEXT,
    needs_review        INTEGER DEFAULT 0               -- 1 when Claude returned null (no confident GL match)
);

-- Indexes

CREATE INDEX IF NOT EXISTS idx_invoices_property_code ON invoices(property_code);
CREATE INDEX IF NOT EXISTS idx_line_items_invoice_id  ON line_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_line_items_assigned_gl ON line_items(assigned_gl_code);
