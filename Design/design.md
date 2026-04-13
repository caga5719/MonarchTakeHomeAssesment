# Invoice Classification Dashboard — Design Plan

## 1. Problem Summary

Monarch receives Amazon Business invoices (PDFs) that each carry **one GL code at the invoice header level**, but individual line items may legitimately belong to different GL categories. For example, a single invoice coded `6702` (APPLIANCE PARTS/SMALL APPLIANCES) might also contain janitorial supplies (`6722`) or plumbing parts (`6730`). The goal is to build a full-stack dashboard that:

- Parses each invoice PDF and extracts header + line-item data
- Classifies each line item against the GL chart of accounts — not just inheriting the invoice-level GL
- Presents breakdowns of GL spend, item counts per GL, and items per property

---

## 2. Data Observations

### Invoices (PDF folder)
Each Amazon Business invoice contains:
- **Header fields**: Invoice number, property code (2–4 chars, e.g. `wrmi`, `fpmn`), invoice-level GL code (e.g. `6702`), purchase date, purchaser name, PO number, total amount
- **Line items**: Description, ASIN, quantity, unit price, subtotal, tax rate
- The invoice-level GL is a best-guess applied at purchase time; it is **not authoritative** per line item

### GL List (1,406 codes, `scode` + `sdesc`)
- Codes span 1000–9999
- Purchasing-relevant codes are concentrated in **6700–6965** (supplies and contractors):
  - `6702` APPLIANCE PARTS/SMALL APPLIANCES
  - `6706` CARPET CLEANING SUPPLIES
  - `6710` ELECTRICAL (INTERIOR/EXTERIOR)
  - `6720` HVAC / BOILER SUPPLIES
  - `6722` JANITORIAL SUPPLIES
  - `6724` LANDSCAPING SUPPLIES
  - `6728` PAINT / DRYWALL
  - `6730` PLUMBING SUPPLIES
  - `6765` OTHER SUPPLIES
  - ... and 30+ more subcategories
- Administrative supplies are in **6300–6365** (e.g. `6332` OFFICE SUPPLIES)
- Rehab/replacement is **7000–7069** (e.g. `7002` RR - APPLIANCES, `7006` RR - CARPET/VINYL)
- Many codes are accounting/payroll/income and irrelevant to purchase classification — the classifier must be scoped to the correct subset

### Property List (351 currently-owned properties)
- Two columns: `Website ID` and `Yardi Code` (the property code on invoices, e.g. `bwoh`, `aaoh`, `CRKS`)
- The "Other Properties" sheet has richer metadata (name, address, state, unit count) for sold/pending properties — useful for display enrichment

---

## 3. Tech Stack Decisions

| Layer | Choice | Why |
|---|---|---|
| Backend API | **FastAPI** (Python) | Async, clean type annotations, auto-generates OpenAPI docs; Python is also the natural fit for PDF parsing and Claude API integration |
| Frontend | **React + Recharts** | Component-based, Recharts integrates well with React and covers all required chart types (bar, pie, table) without heavy dependencies |
| Database | **SQLite + SQLModel** | SQLite for zero-setup local runs; SQLModel (SQLAlchemy + Pydantic) defines the schema as Python classes in `table_models.py`, provides type-safe session management, and supports CRUD for the review queue without raw DDL |
| PDF Parsing | **pdfplumber** | Handles layout-aware extraction better than raw `pdftotext`; the Amazon invoice format is consistent enough that regex + coordinate-based extraction is reliable |
| GL Classification | **Claude API (claude-haiku-4-5)** | Line-item descriptions are natural language product names (e.g., "Dryer Rear Drum Felt Seal Replacement Compatible with Whirlpool…"); semantic understanding is needed to correctly map to GL categories; Haiku is fast and cost-efficient for batch classification |
| Package management | **uv** (Python), **npm** (JS) | uv is fast and handles virtual envs cleanly |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Ingestion Pipeline                      │
│  PDF files → pdfplumber → structured dicts → SQLite             │
│  GL List.xlsx + Property List.xlsx → seeded reference tables     │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                     Classification Service                       │
│  For each unclassified line item:                               │
│    Claude API (Haiku) → returns best-fit GL code + confidence   │
│    Results written back to line_items table                     │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      FastAPI Backend                             │
│  /api/gl-spend          → total $ grouped by GL category        │
│  /api/items-per-gl      → item counts + detail by GL           │
│  /api/items-per-property → item counts + detail by property     │
│  /api/invoices          → paginated invoice list with filters   │
│  /api/invoice/:id       → single invoice with classified items  │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│                      React Dashboard                             │
│  GL Spend Breakdown (bar + pie)                                 │
│  Items Per GL (sortable table + chart)                          │
│  Items Per Property (bar chart + table)                         │
│  Invoice Explorer (search, filter, drill-down to line items)    │
│  Anomaly View (items where AI GL ≠ invoice-level GL)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Database Schema

The schema is defined as SQLModel table classes in `backend/app/table_models.py` — the single source of truth. `init_db()` calls `SQLModel.metadata.create_all(engine)` which creates tables that don't exist yet without touching existing data.

```python
# backend/app/table_models.py (abbreviated)

class GLCode(SQLModel, table=True):       # gl_codes
    scode: int = Field(primary_key=True)
    sdesc: str

class Property(SQLModel, table=True):     # properties
    yardi_code: str = Field(primary_key=True)  # uppercase
    website_id / name / state / unit_count: Optional[...]

class Invoice(SQLModel, table=True):      # invoices
    id: Optional[int] = Field(primary_key=True)
    invoice_number: str = Field(unique=True)
    property_code / invoice_gl_code / invoice_date / due_date /
    purchaser / po_number / subtotal / tax / total_amount / filename: ...
    needs_review: int = 0   # 1 when property_code not in properties table

class LineItem(SQLModel, table=True):     # line_items
    id: Optional[int] = Field(primary_key=True)
    invoice_id: Optional[int] = Field(foreign_key="invoices.id")
    line_number / description / asin / quantity / unit_price /
    subtotal / tax_rate: ...
    assigned_gl_code / assigned_gl_desc / classification_note: Optional[...]
    needs_review: int = 0   # 1 when Claude returned null (no confident GL match)
```

Indexes on `invoices.property_code`, `line_items.invoice_id`, and `line_items.assigned_gl_code` are declared via `__table_args__` on the respective models.

---

## 6. GL Classification Approach

The core insight is that the invoice header GL is one person's best guess at purchase time — often correct for the dominant item type, but not necessarily for every line item on a multi-item invoice.

**Prompt strategy:**
- Feed Claude a **filtered subset** of the GL chart — all codes that could plausibly apply to an Amazon purchase, derived by exclusion rather than hand-picked ranges (see filtering logic below)
- Include the item description, quantity, and context (property code) in the prompt
- Ask for the single best GL code with a one-sentence justification, **or `null` if no provided code is a reasonable fit**
- Use the invoice-level GL as a **hint** ("the buyer coded the whole invoice as X") but not as a constraint

**GL subset filtering logic (exclusion-based):**

Rather than estimating ranges upfront, query the full GL table at runtime and exclude codes whose descriptions match any of these categories — these are provably not Amazon purchase categories:

| Excluded category | Why |
|---|---|
| `sdesc` starts with `TOTAL` or `NET` | Roll-up accounting rows, not real expense lines |
| `sdesc` contains `WAGES`, `PAYROLL`, `BONUS`, `WORKMANS COMP`, `HEALTH INSURANCE`, `401(K)`, `EMPLOYER TAX` | Payroll — never an Amazon purchase |
| `scode` between 5000–5999 | Income accounts |
| `scode` between 6600–6665 | Utility accounts (electric, gas, water, trash) |
| `scode` between 7290–7320 | Interest and mortgage expense |
| `sdesc` contains `INVESTMENT`, `INTEREST EXPENSE`, `MORTGAGE` | Financing accounts |
| `sdesc` contains `DO NOT USE` | Deprecated codes |

Everything remaining (~120–140 codes) is a valid candidate for an Amazon line item and goes into the prompt. This is more complete than a hand-curated range and will catch codes like `6738 HARDWARE`, `6733 TOOLS`, `7114 SUPPLIES`, and `6329 IT EQUIPMENT` that a range-based approach might miss.

**Escape valve — forced hallucination prevention:**

If Claude is constrained to a list and the correct GL code is not in that list, it will silently pick the closest-sounding wrong answer with a confident-looking rationale. To prevent this, the prompt explicitly offers a `null` option:

```
If no code is a reasonable fit for a line item, return gl_code: null and explain
why in the note. Do not guess — a null with a reason is more useful than a
plausible-sounding wrong code.
```

Items returned with `gl_code: null` are stored with `needs_review = TRUE` in the database and surfaced in a dedicated review queue in the dashboard so a human can assign the correct code.

**Why not keyword matching?**
Amazon product descriptions are long, brand-specific strings (e.g., `"ForeverPRO 279220 Clip Kit for Whirlpool Dryer"`). A keyword approach would require maintaining a fragile mapping table and would still miss edge cases. An LLM handles the semantic leap from "Dryer Drum Felt Seal" → APPLIANCE PARTS/SMALL APPLIANCES naturally.

**Cost/performance:**
- Haiku is ~25x cheaper than Sonnet and sufficient for classification tasks
- Batch line items into a single prompt per invoice (one API call per invoice rather than one per line item) to reduce latency and cost

---

## 7. PDF Parsing Strategy

Amazon Business invoices follow a consistent format. The extraction plan:

1. Find the header block: extract `Invoice #`, `GL code`, `Property Code`, `Purchase date`, `PO #`, `Purchased by` using regex on the text stream
2. Find the `Invoice details` section: parse line items as a table (description, qty, unit price, subtotal, tax)
3. Find the summary totals: `Item subtotal before tax`, `Tax`, `Amount due`

Edge cases to handle:
- Multi-page invoices (the `Page N of M` footer signals continuation)
- Promotions/discounts rows (not true line items)
- Items with missing ASINs (some third-party sellers)

---

## 8. Dashboard Views

### Required
| View | Chart Type | Key Metric |
|---|---|---|
| GL Spend Breakdown | Bar + Pie | Total $ per GL category |
| Items Per GL | Sortable table + bar chart | Line item count + $ per GL |
| Items Per Property | Bar chart + table | Line item count + $ per property code |

### Additional views (high value)
| View | Description |
|---|---|
| Invoice Explorer | Searchable/filterable list of all invoices with drill-down to line items and their assigned GL codes |
| GL Mismatch Alerts | Surfaces line items where the AI-assigned GL differs from the invoice-level GL — useful for auditing the buyer's original coding |
| Spend Over Time | Trend line of spending by week/month, optionally filtered by GL or property |
| Top Purchasers | Who is buying what, grouped by `Purchased by` name |

---

## 9. Assumptions

1. **Invoice format is consistent**: All PDFs are Amazon Business invoices with the same header layout. The parser does not need to handle arbitrary vendor formats.
2. **Property codes are case-insensitive**: Invoices use both `aaoh` and `AAOH` style — the matching logic normalizes to uppercase.
3. **Invoice-level GL is a hint, not ground truth**: Classification uses it as context, not as the answer.
4. **Relevant GL codes for purchasing**: Codes in the 6300–6420 (admin), 6700–6965 (supplies/contractors), and 7000–7069 (rehab) ranges cover all Amazon purchase categories. The 1,406-entry full chart includes many accounting, income, and payroll codes that are irrelevant to purchase classification and would confuse the classifier.
5. **Discount/promo rows are skipped**: Negative-value rows (discounts, promotions) are recorded on the invoice but not classified as line items for reporting purposes.

---

## 10. Known Limitations

- **PDF layout brittleness**: If Amazon changes their invoice template, the regex-based parser will need updating. A more robust approach would use a vision model to parse invoice images.
- **Classification confidence is unverified**: There is no ground-truth labeled dataset to measure classification accuracy against. The GL mismatch view helps surface potential errors for human review.
- **Single currency**: All amounts are USD; no currency conversion logic is included.
- **No authentication**: The app is designed to run locally; there is no user auth layer.

---

## 11. What I'd Change for Production

1. **Replace SQLite with PostgreSQL**: Better concurrency, full-text search on descriptions, and easier horizontal scaling.
2. **Async job queue (Celery + Redis)**: PDF ingestion and AI classification are slow operations. In production, these would be background jobs with progress tracking, not synchronous request handlers.
3. **Human-in-the-loop review**: Add a UI to approve/reject AI classifications before they are considered final, with corrections fed back as few-shot examples to improve future prompts.
4. **LLM fine-tuning or embeddings approach**: Build a vector index of GL descriptions and use embedding similarity as a fast first-pass classifier, falling back to the full LLM only for ambiguous cases.
5. **Invoice format generalization**: Support vendor invoices beyond Amazon Business (different PDF layouts) using a vision model (Claude's vision capability) as a universal parser.
6. **Audit trail**: Every classification decision logged with the prompt, response, and model version — required for financial auditability.
7. **Integration with Yardi**: Export classified line items in the format Yardi expects for PO matching, closing the loop with the existing upload process.
