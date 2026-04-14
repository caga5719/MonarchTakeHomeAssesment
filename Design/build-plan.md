# Invoice Classification Dashboard — Multiphase Build Plan

Each phase is designed to be self-contained: a fresh context window can read this file plus the phase's listed prerequisite files and immediately know what to build, what decisions have already been made, and what "done" looks like.

---

## Directory Structure (target at completion)

```
TakeHomeAssesment/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── database.py          # SQLite connection + session
│   │   ├── table_models.py      # SQLModel table definitions (schema source of truth)
│   │   ├── models.py            # Pydantic response models
│   │   ├── auth.py              # JWT utilities + get_current_user dependency
│   │   ├── seed.py              # Seeds GL codes + properties from xlsx files
│   │   ├── ingest.py            # PDF parsing pipeline
│   │   ├── classify.py          # Claude API classification service
│   │   └── routers/
│   │       ├── auth.py          # /api/auth/token, /api/auth/register, /api/users/me
│   │       ├── gl.py            # /api/gl-spend, /api/items-per-gl
│   │       ├── properties.py    # /api/items-per-property
│   │       ├── invoices.py      # /api/invoices, /api/invoices/{id}
│   │       └── summary.py       # /api/summary, /api/mismatches
│   ├── pyproject.toml
│   └── .env.example             # ANTHROPIC_API_KEY placeholder
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/                 # Typed fetch wrappers
│   │   ├── components/          # Shared UI (Layout, Nav, Charts, Table)
│   │   └── pages/
│   │       ├── GLSpend.tsx
│   │       ├── ItemsPerGL.tsx
│   │       ├── ItemsPerProperty.tsx
│   │       ├── InvoiceExplorer.tsx
│   │       ├── Mismatches.tsx
│   │       └── Login.tsx
│   │   ├── context/
│   │   │   └── AuthContext.tsx
│   ├── package.json
│   └── vite.config.ts
├── GL List.xlsx
├── Property List.xlsx
├── Invoices/                    # ~hundreds of Amazon PDFs
├── invoice_data.db              # SQLite (created/populated in phases 1–3)
├── Design/
│   ├── design.md
│   └── build-plan.md            # this file
└── README.md                    # written in Phase 6
```

---

## Phase 1 — Project Scaffold & Reference Data

**Goal**: Create the project skeleton, establish the database schema, and populate the two reference tables (GL codes and properties) so every subsequent phase has stable data to work against.

**Prerequisites**: None. Start here.

**Context to load**:
- `Design/design.md` (full architecture rationale)
- `GL List.xlsx` (1,406 GL codes: `scode`, `sdesc`)
- `Property List.xlsx` (`Currently Owned` sheet: `Website ID`, `Yardi Code`; `Other Properties` sheet has richer metadata)

### Tasks

1. **Initialize backend with uv**
   ```bash
   cd backend
   uv init --python 3.12
   uv add fastapi uvicorn sqlmodel pdfplumber openpyxl anthropic python-dotenv
   ```

2. **Write `table_models.py`** — SQLModel table classes (replaces `schema.sql` as the schema source of truth):
   - `GLCode` → `gl_codes (scode INTEGER PK, sdesc TEXT)`
   - `Property` → `properties (yardi_code TEXT PK, website_id, name, state, unit_count)`
   - `Invoice` → `invoices (id PK, invoice_number UNIQUE, property_code, invoice_gl_code, dates, amounts, filename, needs_review INT DEFAULT 0)`
   - `LineItem` → `line_items (id PK, invoice_id FK, line_number, description, asin, qty, prices, assigned_gl_code, assigned_gl_desc, classification_note, needs_review INT DEFAULT 0)`
   - Declare indexes via `__table_args__` on `Invoice` and `LineItem`

3. **Write `database.py`** — SQLModel engine pointed at `../invoice_data.db` with `check_same_thread=False`; `init_db()` calls `SQLModel.metadata.create_all(engine)`; `get_session()` yields a `Session` for FastAPI dependency injection

4. **Write `seed.py`** — reads both xlsx files with openpyxl and upserts into `gl_codes` and `properties`:
   - `GL List.xlsx` → sheet `ySQL_0_10042026110022 (1)`, columns `scode` / `sdesc`
   - `Property List.xlsx` → `Currently Owned` sheet (cols: Website ID, Yardi Code — only two are populated), then enrich with `Other Properties` sheet where yardi_code matches (for name, state, unit_count)
   - Normalize `yardi_code` to **uppercase** on insert (invoices use mixed case; normalizing here avoids repeated transforms)

5. **Initialize React frontend with Vite**
   ```bash
   cd frontend
   npm create vite@latest . -- --template react-ts
   npm install recharts react-router-dom
   ```
   Create a minimal `App.tsx` with placeh

6. **Write `.env.example`**: `ANTHROPIC_API_KEY=sk-ant-...`

### Done When
- `python backend/app/seed.py` runs without errors
- `SELECT COUNT(*) FROM gl_codes` → 1404 (2 rows in the xlsx have a null description and are skipped — a code with no label can't be used for classification)
- `SELECT COUNT(*) FROM properties` → ≥ 351
- `npm run dev` in `frontend/` shows a blank page without console errors

---

## Phase 2 — PDF Ingestion Pipeline

**Goal**: Parse every invoice PDF in `Invoices/` and write structured records to the `invoices` and `line_items` tables.

**Prerequisites**: Phase 1 complete — database schema exists and reference tables are populated.

**Context to load**:
- `Design/design.md` sections 7 (PDF parsing strategy) and 5 (schema)
- `backend/app/schema.sql`
- `backend/app/database.py`
- Sample invoice text output (run `pdftotext` on 2-3 invoices to verify field positions before coding the parser)

### Known Invoice Structure (from pre-analysis)

Header fields appear in this order in the text stream:
```
Invoice # {invoice_number} | {date}
...
PO #          {po_number}
GL code       {gl_code}
Property Code {property_code}
...
```

Line items appear after `Invoice details` header, one item per block:
```
{line_number}  {description (multi-line)}
               ASIN: {asin}
               Sold by: {seller}
               Order # {order_number}    Qty   Unit price   Item subtotal before tax   Tax
                                         {qty}  ${price}    ${subtotal}               {tax_rate}%
```

Discount rows look like: `Promotions & discounts   (${amount})`  — skip these for line-item classification.

Summary block at end: `Item subtotal before tax`, `Tax`, `Amount due`.

### Tasks

1. **Write `ingest.py`**:
   - `parse_invoice(pdf_path: Path) -> dict` — returns `{header: {...}, line_items: [...]}`
   - Use `pdfplumber` to extract full text page by page, concatenate, then apply regex patterns
   - Regex patterns needed:
     - `r"Invoice # ([\w-]+)"` → invoice_number
     - `r"PO #\s+(\d+)"` → po_number
     - `r"GL code\s+(\d+)"` → invoice_gl_code
     - `r"Property Code\s+(\w+)"` → property_code (normalize to uppercase)
     - `r"Purchase date\s+([\d-]+(?:\w+\s+\d+,\s+\d+)?)"` → invoice_date (parse to date)
     - `r"Payment due by (.+)"` → due_date
     - `r"Purchased by\s+(.+)"` → purchaser
     - `r"Amount due\s+\$([\d,.]+)"` → total_amount
   - Line item extraction: split on `\n{digit}+\s` boundaries after the `Invoice details` line; parse each block for qty, unit price, subtotal, tax_rate
   - `ingest_all(invoices_dir: Path)` — iterates PDFs, calls `parse_invoice`, skips already-ingested invoice numbers (check `invoices` table), writes to DB
   - Print a summary: `Processed N invoices, M line items, K skipped (already in DB), P flagged needs_review`

2. **Handle edge cases**:
   - Multi-page: `pdfplumber` reads all pages; concatenate before parsing
   - Missing ASIN: some third-party items have no ASIN — store as `NULL`
   - Discount rows: detect by `Promotions & discounts` keyword on the line; skip entirely (not stored as line items)
   - Property code not in `properties` table: set `invoices.needs_review = 1` and **do not write any line items** — the invoice as a whole must be manually reviewed before it can be routed or classified

3. **Add a `--dry-run` flag** that prints parsed data without writing to DB — useful for debugging

### Done When
- `python backend/app/ingest.py` completes without unhandled exceptions
- `SELECT COUNT(*) FROM invoices` matches the number of PDFs in `Invoices/`
- `SELECT COUNT(*) FROM line_items` > 0
- `SELECT COUNT(*) FROM invoices WHERE needs_review = 1` — print this number; these invoices have no line items and require manual property-code resolution
- `SELECT COUNT(*) FROM line_items li JOIN invoices i ON i.id = li.invoice_id WHERE i.needs_review = 1` → 0 (no line items attached to flagged invoices)
- Spot-check 3 invoices: query `SELECT * FROM line_items WHERE invoice_id = X` and compare to the source PDF manually
- `line_items.assigned_gl_code` is NULL for all rows (classification not yet done)

---

## Phase 3 — AI Classification Service

**Goal**: For every unclassified line item, call Claude (Haiku) to assign the best-fit GL code from the purchasing-relevant subset of the GL chart, or flag it for human review if no code is a confident match. Write results back to `line_items`.

**Prerequisites**: Phase 2 complete — `line_items` table is fully populated with NULL `assigned_gl_code`.

**Context to load**:
- `Design/design.md` section 6 (classification approach — read the full section, it was updated)
- `backend/app/database.py`

### GL Subset Filtering (exclusion-based, not range-based)

Do NOT use hardcoded ranges. Instead, `load_purchasing_gl_codes()` queries all codes and excludes:

```python
EXCLUDE_PATTERNS = [
    "TOTAL", "NET ",          # roll-up rows
    "WAGES", "PAYROLL", "BONUS", "WORKMANS COMP",
    "HEALTH INSURANCE", "401(K)", "EMPLOYER TAX",  # payroll
    "INVESTMENT", "INTEREST EXPENSE", "MORTGAGE",  # financing
    "DO NOT USE",             # deprecated
]
EXCLUDE_SCODE_RANGES = [
    (5000, 5999),   # income accounts
    (6600, 6665),   # utilities
    (7290, 7320),   # interest/mortgage
]

def load_purchasing_gl_codes(db) -> list[dict]:
    rows = db.execute("SELECT scode, sdesc FROM gl_codes ORDER BY scode").fetchall()
    result = []
    for scode, sdesc in rows:
        if sdesc is None:
            continue
        if any(p in sdesc.upper() for p in EXCLUDE_PATTERNS):
            continue
        if any(lo <= scode <= hi for lo, hi in EXCLUDE_SCODE_RANGES):
            continue
        result.append({"scode": scode, "sdesc": sdesc})
    return result
```

This produces ~120–140 codes and captures edge cases like `6738 HARDWARE`, `6733 TOOLS`, `7114 SUPPLIES`, and `6329 IT EQUIPMENT` that hand-picked ranges would miss.

### Tasks

1. **Update `schema.sql`** — add `needs_review BOOLEAN DEFAULT 0` to `line_items`

2. **Write `classify.py`**:

   - `load_purchasing_gl_codes(db) -> list[dict]` — exclusion-based filter as above
   - `build_prompt(invoice_gl: int, invoice_gl_desc: str, line_items: list[dict], gl_codes: list[dict]) -> str`:
     ```
     You are a property management accounting assistant.

     The invoice was coded at the header level as GL {invoice_gl} ({invoice_gl_desc}).
     Use this as a hint, but classify each line item independently based on its description.

     GL chart (purchasing-relevant codes only):
     {scode}: {sdesc}
     ...

     Classify each line item. Return a JSON array — one object per item, in any order:
     [{"id": <line_item_id>, "gl_code": <scode or null>, "note": "<one sentence reason>"}]

     IMPORTANT: If no code is a reasonable fit for a line item, return gl_code: null
     and explain why in the note. Do not guess — a null with a reason is more useful
     than a plausible-sounding wrong code.

     Line items:
     1. [ID {id}] {description} (qty: {qty}, unit price: ${unit_price})
     ...
     ```
   - `classify_invoice(invoice_id, db, client)`:
     - Fetches all unclassified, non-discount items for the invoice
     - Calls Claude, parses JSON response
     - For items with a returned `gl_code`: sets `assigned_gl_code`, looks up and sets `assigned_gl_desc`, sets `needs_review = FALSE`
     - For items with `gl_code: null`: sets `assigned_gl_code = NULL`, stores the note in `classification_note`, sets `needs_review = TRUE`
     - Updates all items in a single transaction
   - `classify_all(db, client)` — iterates all invoices with unclassified items; calls `classify_invoice`; prints progress including count of `needs_review` items
   - Use `anthropic.Anthropic()` client with model `claude-haiku-4-5-20251001`
   - Wrap each API call in try/except; on failure log the invoice_id and continue

3. **Prompt engineering notes**:
   - Keep the GL list as `scode: sdesc` pairs — descriptions are self-evident
   - Ask for JSON with `id` field so ordering doesn't matter
   - Use `max_tokens=1500` — slightly larger budget now that null-path notes can be verbose
   - Skip discount/promo rows (negative subtotal or "Promotions" keyword) — do not include in prompt

4. **Validation**:
   - After `classify_all` completes:
     - `SELECT COUNT(*) FROM line_items WHERE assigned_gl_code IS NULL AND needs_review = 0 AND quantity IS NOT NULL` → should be 0 (every classifiable item has either a code or is flagged)
     - `SELECT COUNT(*) FROM line_items WHERE needs_review = 1` → print this number; some is expected and healthy
   - Sample 10 random classified items and print `description | assigned_gl_code | assigned_gl_desc | classification_note`
   - Sample all `needs_review = 1` items — review the notes to confirm Claude's reasoning for flagging them makes sense

### Done When
- All non-discount line items have either a non-NULL `assigned_gl_code` or `needs_review = TRUE`
- Sampled classifications look semantically correct (e.g., dryer parts → 6702 APPLIANCE PARTS, balloons → 6516 RESIDENT/PUBLIC RELATIONS, weather stripping → 6708 DOORS/SUPPLIES)
- `needs_review` items have coherent `classification_note` explaining why no code fit
- No unhandled exceptions during the full run

---

## Phase 4 — FastAPI REST API

**Goal**: Expose all data the frontend needs through typed REST endpoints. The frontend will talk exclusively to this API — no direct DB access from the browser.

**Prerequisites**: Phase 3 complete — all line items classified.

**Context to load**:
- `Design/design.md` section 4 (architecture diagram)
- `backend/app/database.py`
- `backend/app/models.py` (or schema.sql if not using ORM)

### Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/summary` | `{total_invoices, total_spend, total_line_items, properties_count, top_gl, top_property, needs_review_count}` |
| GET | `/api/gl-spend` | `[{gl_code, gl_desc, total_spend, item_count}]` sorted by total_spend desc |
| GET | `/api/items-per-gl` | `[{gl_code, gl_desc, item_count, total_spend, invoices: [{invoice_number, property_code, description, subtotal}]}]` |
| GET | `/api/items-per-property` | `[{property_code, item_count, total_spend, invoice_count}]` sorted by total_spend desc |
| GET | `/api/invoices` | Paginated: `{items: [...], total, page, page_size}`. Query params: `?property=`, `?gl=`, `?search=`, `?page=`, `?page_size=` |
| GET | `/api/invoices/{invoice_number}` | Full invoice with `line_items` array (each item includes `assigned_gl_code`, `assigned_gl_desc`, `needs_review`) |
| GET | `/api/mismatches` | `[{invoice_number, property_code, invoice_gl_code, invoice_gl_desc, line_item_desc, assigned_gl_code, assigned_gl_desc, subtotal}]` — rows where `assigned_gl_code != invoice_gl_code` AND `needs_review = FALSE` |
| GET | `/api/needs-review` | `[{id, invoice_number, property_code, description, classification_note, invoice_gl_code, invoice_gl_desc}]` — items where `needs_review = TRUE`; no GL was confident enough to assign |

### Tasks

1. **Write `backend/app/main.py`**:
   - `FastAPI()` instance, mount routers, add CORS middleware (allow `http://localhost:5173` for Vite dev server)
   - Startup event: call `init_db()` to ensure schema exists

2. **Write the four router files** under `backend/app/routers/`:
   - Use `Depends(get_session)` from `app.database` — no local `get_db()` needed in each router
   - Analytical aggregation queries (GROUP BY, SUM, JOIN) use `session.execute(text(...)).mappings()` with `:name` named parameters; simple lookups use `session.exec(select(...))`
   - All dollar amounts should be rounded to 2 decimal places before returning
   - Return `[]` not errors when no data exists

3. **Write `backend/app/models.py`** — Pydantic response models for each endpoint (for auto-generated docs and type safety)

4. **Test all endpoints manually**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   curl http://localhost:8000/api/summary
   curl http://localhost:8000/api/gl-spend
   curl "http://localhost:8000/api/invoices?page=1&page_size=10"
   ```

### Done When
- `uvicorn app.main:app --reload` starts without import errors
- All 7 endpoints return valid JSON
- `/api/mismatches` returns at least some results (mismatches are expected and normal)
- FastAPI auto-docs at `http://localhost:8000/docs` show all endpoints with correct schemas

---

## Phase 5 — React Frontend: Core Dashboard

**Goal**: Build the three required dashboard views wired to the live FastAPI backend. All charts use real data.

**Prerequisites**: Phase 4 complete — API running at `localhost:8000`.

**Context to load**:
- `Design/design.md` section 8 (dashboard views table)
- `Design/build-plan.md` Phase 4 endpoint table (above)
- `frontend/src/` scaffold from Phase 1

### Tasks

1. **Write `frontend/src/api/index.ts`** — typed fetch wrappers for every endpoint:
   ```ts
   export const getGLSpend = () => fetch('/api/gl-spend').then(r => r.json())
   export const getItemsPerGL = () => fetch('/api/items-per-gl').then(r => r.json())
   // etc.
   ```
   Configure `vite.config.ts` proxy: `'/api' → 'http://localhost:8000'` so no CORS issues in dev.

2. **Write shared components** (`frontend/src/components/`):
   - `Layout.tsx` — top nav with links to each page, main content area
   - `StatCard.tsx` — small card for summary numbers (total spend, invoice count, etc.)
   - `LoadingSpinner.tsx` — used while fetching
   - `DataTable.tsx` — reusable sortable table with column config prop

3. **GL Spend Breakdown page** (`pages/GLSpend.tsx`):
   - Top: 4 `StatCard` components (total invoices, total spend, unique GLs used, properties)
   - Bar chart: GL code on X axis, total spend on Y axis (top 15 by spend)
   - Pie chart: same data, showing proportion — place side-by-side with bar chart
   - Below charts: full sortable `DataTable` with all GL codes (GL code, description, item count, total spend)

4. **Items Per GL page** (`pages/ItemsPerGL.tsx`):
   - Bar chart: item count per GL (top 15)
   - Expandable table: each row is a GL category; click to expand and see the individual line items within it (invoice number, property, description, subtotal)

5. **Items Per Property page** (`pages/ItemsPerProperty.tsx`):
   - Horizontal bar chart: property code on Y axis, total spend on X axis (more readable for many properties)
   - Sortable table: property code, item count, invoice count, total spend

6. **`App.tsx`**: Set up `react-router-dom` with routes for `/`, `/items-per-gl`, `/items-per-property`

### Done When
- `npm run dev` starts, all three pages load without errors
- Charts render with real data (not hardcoded)
- Tables are sortable
- The three required views satisfy the spec: GL spend breakdown, items per GL, items per property

---

## Phase 6 — Extended Views, Polish, and README

**Goal**: Add the bonus views, finalize styling, ensure the app runs cleanly end-to-end from a fresh clone, and write the README.

**Prerequisites**: Phase 5 complete — all required views working.

**Context to load**:
- `Design/design.md` sections 8 (extended views) and 11 (production considerations)
- `Design/build-plan.md` Phase 4 endpoint table (mismatches endpoint)

### Tasks

1. **Invoice Explorer page** (`pages/InvoiceExplorer.tsx`):
   - Search bar (filters by invoice number, property code, or purchaser name) — debounced, calls `/api/invoices?search=`
   - Filter dropdowns: by property code, by invoice-level GL
   - Paginated table of invoices (invoice #, date, property, purchaser, total, invoice GL)
   - Click a row → expand (or navigate) to show all line items with their **AI-assigned GL code** vs the invoice-level GL — highlight mismatches in amber

2. **GL Mismatch view** (`pages/Mismatches.tsx`):
   - Intro text explaining what a mismatch means (AI disagrees with buyer's coding)
   - Table: invoice number, property, item description, invoice GL (original), AI-assigned GL, subtotal
   - Color-code: same category family (e.g., both in 67xx) = yellow; different category family = red
   - Summary stat: "X of Y line items (Z%) were reclassified by AI"

3. **Polish**:
   - Consistent color palette using Recharts' `COLORS` array
   - Responsive layout (nav collapses on small screens)
   - Empty states (show a message when no data matches a filter)
   - Error boundaries around chart components so one failed fetch doesn't crash the page

4. **End-to-end startup script** (`run.sh`):
   ```bash
   #!/bin/bash
   set -e
   cd backend && uv run python app/seed.py && uv run python app/ingest.py && uv run python app/classify.py
   uv run uvicorn app.main:app --port 8000 &
   cd ../frontend && npm run build && npx serve dist -l 3000
   ```
   Or simpler: document how to run backend + frontend separately in README.

5. **Write `README.md`** (manually written, not generated) covering:
   - What the app does
   - How to run it (step-by-step: set `ANTHROPIC_API_KEY`, run seed/ingest/classify, start API, start frontend)
   - Architecture and design decisions (reference `Design/design.md`)
   - Assumptions made about the data
   - Known limitations
   - What I'd build or change for production

### Done When
- Invoice Explorer search works with real queries
- Mismatch view loads and shows meaningful data
- `README.md` is complete and accurate
- The app can be started from scratch following only the README instructions
- All four bonus views are accessible from the nav

---

## Phase 7 — User Profiles, Authentication & Role-Based Data Scoping

**Goal**: Add a lightweight username/password authentication layer with JWT session management. Users log in to receive a signed token; all data endpoints are protected and automatically scoped to the authenticated user's role and property assignment.

**Prerequisites**: Phase 6 complete — full dashboard running. Backend at `localhost:8000`, frontend at `localhost:5173`.

**Context to load**:
- `Design/design.md` section 9 (full auth design — read the entire section)
- `backend/app/table_models.py` (existing schema to extend)
- `backend/app/database.py` (session dependency)
- `backend/app/main.py` (router registration)

### New dependencies

```bash
cd backend
uv add passlib[bcrypt] python-jose[cryptography]
```

Add to `backend/.env` (and `.env.example`):
```
JWT_SECRET=replace-with-a-long-random-string
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=8
```

### Tasks

1. **Extend `table_models.py`** — add the `User` model:
   ```python
   class User(SQLModel, table=True):
       __tablename__ = "users"

       id: Optional[int] = Field(default=None, primary_key=True)
       username: str = Field(unique=True)
       hashed_password: str
       name: str
       role: Optional[str] = None            # 'admin' | 'manager' | 'operations'
       property_code: Optional[str] = None   # soft ref to properties.yardi_code (uppercase)
   ```
   `init_db()` will create the table automatically on next startup.

2. **Write `backend/app/auth.py`** — auth utilities:
   - `pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")`
   - `hash_password(plain: str) -> str` — wraps `pwd_context.hash()`
   - `verify_password(plain: str, hashed: str) -> bool` — wraps `pwd_context.verify()`
   - `create_access_token(data: dict) -> str` — signs a JWT with `JWT_SECRET`, sets `exp` to `now + JWT_EXPIRE_HOURS`
   - `get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User`:
     - Decodes the JWT; raises `HTTPException(401)` if invalid or expired
     - Returns the `User` row from DB (using `sub` / `user_id` from payload)
   - `oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")`

3. **Write `backend/app/routers/auth.py`** — auth endpoints:
   - `POST /api/auth/token`:
     - Accepts `OAuth2PasswordRequestForm` (standard form body: `username`, `password`)
     - Looks up user by `username`; calls `verify_password`; raises `401` on failure
     - Calls `create_access_token({"sub": user.username, "user_id": user.id, "role": user.role, "property_code": user.property_code})`
     - Returns `{"access_token": token, "token_type": "bearer"}`
   - `POST /api/auth/register`:
     - Accepts `{username, password, name, role, property_code}` (JSON body)
     - Validates: `username` unique; at least one of `role` or `property_code` non-null
     - Calls `hash_password(password)`; inserts `User`; returns created user (omit `hashed_password` from response)
   - `GET /api/users/me`:
     - Depends on `get_current_user`; returns the current user's profile

4. **Update all data routers** — add `current_user: User = Depends(get_current_user)` to every endpoint in `routers/gl.py`, `routers/properties.py`, `routers/invoices.py`, and `routers/summary.py`:
   - Extract a `property_filter` helper:
     ```python
     def property_filter(current_user: User) -> Optional[str]:
         if current_user.role == "admin" or current_user.property_code is None:
             return None   # unscoped
         return current_user.property_code.upper()
     ```
   - In every query that joins `invoices`, add `AND inv.property_code = :pc` when `property_filter` returns a non-None value
   - Use SQLAlchemy named parameters (`:pc`) — never string-format user data into queries

5. **Register the auth router in `main.py`**:
   ```python
   from app.routers import auth
   app.include_router(auth.router)
   ```

6. **Frontend — `AuthContext`** (`frontend/src/context/AuthContext.tsx`):
   - Holds `{ user: DecodedUser | null, token: string | null, login, logout }`
   - On mount: reads `localStorage.getItem("jwt_token")`; decodes the payload with `jwt-decode`; checks `exp`; sets context or clears if expired
   - `login(token)`: stores in `localStorage`, decodes and sets user in context
   - `logout()`: clears `localStorage`, sets user/token to null, calls `navigate("/login")`
   - Add `jwt-decode` to frontend dependencies: `npm install jwt-decode`

7. **Frontend — Login page** (`frontend/src/pages/Login.tsx`):
   - Username + password form
   - Submits as `application/x-www-form-urlencoded` to `POST /api/auth/token` (OAuth2 standard)
   - On success: calls `AuthContext.login(token)`; redirects to `/`
   - On failure: shows inline error message

8. **Frontend — `api/index.ts` updates**:
   - Add a `getAuthHeaders()` helper that returns `{ Authorization: "Bearer <token>" }` when a token is in `localStorage`
   - Wrap every `fetch` call to include these headers
   - Add a response interceptor: if any response returns `401`, call `AuthContext.logout()`

9. **Frontend — Route protection** (`frontend/src/App.tsx`):
   - Wrap all dashboard routes in a `<ProtectedRoute>` component that reads `AuthContext`; redirects to `/login` if no valid user
   - Add `/login` and `/register` as public routes (not wrapped)

10. **Frontend — Conditional rendering updates**:
    - In `GLSpend.tsx`: hide the Properties `StatCard` when `user.role !== 'admin'`
    - In `Layout.tsx` / nav: hide the "Items Per Property" nav link when `user.role !== 'admin'`
    - In `ItemsPerProperty.tsx`: render a "Not authorized" message if a non-admin somehow navigates there directly

### Done When
- `POST /api/auth/register` creates a user and returns a profile (without `hashed_password`)
- `POST /api/auth/token` with correct credentials returns a JWT; invalid credentials return `401`
- All data endpoints return `401` when called without a valid `Authorization` header
- An admin user sees all properties and all data across every page
- A manager/operations user sees only data for their `property_code`; the Items Per Property page is hidden from their nav
- The login page redirects to `/` on success; an expired or missing token redirects to `/login`
- JWT secret is loaded from `backend/.env` — not hardcoded in any source file

---

## Cross-Phase Notes

### State shared between phases
- `invoice_data.db` is the handoff artifact between phases 1–3 and phases 4–6
- Never hardcode invoice numbers, GL codes, or property codes — always read from DB
- The `ANTHROPIC_API_KEY` must be in `backend/.env` before Phase 3

### Classification is idempotent
`classify.py` only processes rows where `assigned_gl_code IS NULL` — safe to rerun if interrupted.

### Ingestion is idempotent
`ingest.py` checks for existing `invoice_number` before inserting — safe to rerun.

### GL code normalization
The invoice PDFs use integer GL codes (e.g., `6702`). The GL list uses integer `scode`. Always compare as integers, not strings.

### Property code normalization
Invoice PDFs use mixed case (`wrmi`, `CCMO`). Normalize to **uppercase** at ingest time and store uppercase in `invoices.property_code`. The `properties.yardi_code` column should also be uppercase (done in Phase 1 seed). All API queries use `UPPER()` or normalized values — never raw case-sensitive comparison.
