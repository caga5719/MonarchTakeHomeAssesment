# Monarch Invoice GL Dashboard

A full-stack dashboard that parses Amazon Business invoice PDFs, uses Claude AI to classify each line item against Monarch's GL chart of accounts, and presents the results in an interactive web interface.

---

## What the App Does

Amazon Business invoices carry a single GL code at the invoice level, but individual line items often belong to different GL categories. This app solves that by:

1. **Parsing** each invoice PDF to extract header fields (property code, PO number, invoice-level GL, purchaser) and line items (description, qty, unit price, subtotal, tax rate)
2. **Classifying** each line item individually using Claude AI against the full GL chart — so a 12-item invoice coded `6516` at the header level might correctly resolve to `6722` (Janitorial Supplies), `6765` (Other Supplies), and `6516` (Resident/Public Relations) across its items
3. **Persisting** everything to a local SQLite database
4. **Serving** the data through a REST API to a React dashboard with four views

---

## How to Run It

### Prerequisites

- Python 3.13+ with [uv](https://docs.astral.sh/uv/) installed
- Node.js 18+
- An Anthropic API key with available credits

### 1. Backend

```bash
cd backend

# Copy and fill in your API key
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY=your_key_here

# Install dependencies and start the server
uv run uvicorn main:app --reload --port 8000
```

The server starts at `http://localhost:8000`. On startup it automatically:
- Initialises the SQLite database schema (`invoice_data.db`)
- Loads all GL accounts from `GL List.xlsx`
- Loads all properties from `Property List.xlsx`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`.

### 3. Process Invoices

Navigate to the **Processing** tab in the dashboard and click **Process Pending Invoices**, or trigger via the API directly:

```bash
curl -X POST http://localhost:8000/api/process
```

Processing runs in the background. The status bar on the Processing page polls every 3 seconds and updates automatically. Already-processed invoices are skipped on subsequent runs — safe to re-run at any time.

### 4. Stopping the Servers

**Backend:** Press `Ctrl+C` in the terminal running uvicorn, or kill by port:
```bash
lsof -ti :8000 | xargs kill -9
```

**Frontend:** Press `Ctrl+C` in the terminal running `npm run dev`, or kill by port:
```bash
lsof -ti :5173 | xargs kill -9
```

> **Note on stopping mid-processing:** It is safe to stop the backend at any time. Each invoice is written in a single database transaction — if the server stops mid-invoice, that invoice's write is rolled back and it will be picked up again on the next run. No partial data will be left in the database.

---

## Architecture & Design Decisions

```
frontend/              React + TypeScript + Vite + Tailwind + Recharts
backend/
  app/
    main.py            FastAPI app, CORS, lifespan hooks
    api/routes.py      REST endpoints
    core/
      config.py        Environment config via .env
      database.py      SQLite schema + connection context manager
    models/
      schemas.py       Pydantic response models
    services/
      loader.py        Reads GL List.xlsx + Property List.xlsx into DB
      parser.py        pdfplumber PDF extraction (header + line items)
      classifier.py    Claude API GL classification
      processor.py     Orchestrates scan → parse → classify → persist
```

### Why SQLite?

This is a local tool operating on a fixed dataset of invoices. SQLite requires zero setup, is portable (single file), and handles hundreds of invoices with thousands of line items without any performance concern. For a production deployment with concurrent users or continuous ingestion, PostgreSQL would be the right choice.

### Why FastAPI + Python?

Python has the best ecosystem for PDF parsing (`pdfplumber`) and the Anthropic SDK is first-class. FastAPI provides async background task support out of the box — used to trigger a long-running processing job from the UI without blocking the HTTP response.

### Why one Claude call per invoice (not per line item)?

Batching all line items for an invoice into a single prompt keeps API costs proportional to invoice count rather than line item count. It also gives Claude cross-item context — seeing that 8 of 12 items on an invoice are clearly janitorial supplies helps it reason more confidently about the ambiguous 9th. The full GL chart is included in every call.

### Why pdfplumber?

pdfplumber produces clean text output from the structured Amazon Business PDF format and handles multi-page invoices naturally. The consistent invoice layout makes regex-based field extraction reliable.

### PDF Parsing Strategy

The parser uses `re.finditer` to locate line item starts by matching small integers (1–99) at the beginning of a line. This correctly bounds the match to actual line numbers and avoids false positives from item descriptions that start with large numbers (e.g. "100 Pack Rubber Ducks"). Header fields are extracted with targeted regex patterns against the full concatenated page text.

### Manual Intervention Flag

Invoices where the property code is missing or doesn't match any entry in the Properties reference list are flagged `manual_intervention = true`. These appear with a **Review** badge in the Invoices table so staff can investigate without the flag being buried in data.

### GL Confidence Levels

Claude returns a confidence level (`high`, `medium`, `low`) for each line item classification. These are stored and surfaced in the UI with colour-coded badges. Items where the AI-assigned GL differs from the invoice-level GL are highlighted with an indicator (↑), drawing attention to reclassified items.

---

## Assumptions

- **Invoice format is consistent.** The parser is tuned to the Amazon Business PDF layout. Invoices from other vendors would require parser changes.
- **Property codes are case-insensitive.** All codes are normalised to lowercase. The reference list had mixed casing (`CRKS`, `crmi`, `bwoh`).
- **Some invoices have multiple property codes** (e.g. `BPAL/CHAL`). The parser captures only the first code.
- **The GL chart is the source of truth.** The classifier is constrained to codes in the chart; if a match cannot be found, it falls back to the invoice-level GL with `low` confidence.
- **ASINs are 10-character alphanumeric strings.** Items without a parseable ASIN store `null`.
- **Discounts and promotional lines are not line items.** Rows matching "promotion" or "discount" are excluded from parsing and classification.

---

## Known Limitations

- **No real-time processing feedback.** The Processing page polls the status endpoint every 3 seconds. For very large volumes a WebSocket stream would be better.
- **Parser is regex-based.** Works well on the provided Amazon Business format but will break on invoices with significantly different layouts.
- **Property names are not available.** The Property List only contains Yardi codes with no human-readable names — the dashboard shows codes in place of names.
- **No authentication.** Designed for local use. The API has no auth layer.
- **No re-classification UI.** If a GL assignment is wrong there is no way to correct it in the dashboard — the database would need to be edited directly.
- **Background processing is in-process.** If the server restarts mid-run, the job stops. Incomplete invoices are simply not written to the DB and will be picked up on the next run.

---

## What I'd Build or Change for Production

### Infrastructure
- Replace SQLite with **PostgreSQL** — concurrent writers, proper transactions, production-grade reliability
- Add a **job queue** (Celery + Redis, or a managed service like AWS SQS) for invoice processing — retries, dead-letter queues, real-time progress over WebSocket
- **Containerise** with Docker Compose: `backend`, `frontend`, `db`, `worker` services, all wired together with a single `docker compose up`
- **CI/CD pipeline** with automated tests gating deploys

### Features
- **Manual GL override UI** — let staff correct a misclassification in the dashboard; store the override separately so it survives re-processing
- **Yardi export** — generate the coded line-item data in whatever format Yardi's import expects, closing the loop with the existing upload pipeline
- **Confidence threshold review queue** — surface all `low`-confidence classifications in one place for human sign-off before they flow downstream
- **Property name lookup** — join against a richer property reference (name, address, manager contact) for more useful dashboard labels
- **Authentication** — at minimum an API key header; ideally SSO via the organisation's identity provider
- **Audit log** — track who triggered processing, when, and what was changed or overridden

### Parser
- Evaluate **Claude's vision capability** or a dedicated document-AI API as a drop-in replacement for the regex parser — more robust to layout variation and handles scanned documents
- Add a **parser confidence score** — flag invoices where key fields could not be extracted so they can be reviewed before GL classification is run
