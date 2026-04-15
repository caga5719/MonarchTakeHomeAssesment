# Monarch Invoice Classifier - Carlos Garcia

## What the App Does

This is an invoice accounting platform that works to extract and classify invoice and line item data, following the steps below:

- Parse PDF Amazon Business Invoices for invoice-specific data like the purchaser and the property code, as well as extracting line item data like the line item description and quantity of items purchased.
- Classify the extracted line item data using Claude (Haiku) against a subset of relevant general ledger accounts.
- Provide a GL Spend Breakdown, Items Per GL Category, Items Per Property, Invoice Explorer, and Invoice and Line Item Review dashboard views.

## To run the app

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+ with npm
- An [Anthropic API key](https://console.anthropic.com/)

### 1. Set Up Environment Variables

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set:
# ANTHROPIC_API_KEY=sk-ant-...
# JWT_SECRET=replace-with-a-long-random-string
```

### 2. Install Backend Dependencies

```bash
cd backend
uv sync
```

### 3. Seed Reference Data (GL codes + Properties)
 ***NOTE: If the database is cleared, this will need to be run before starting up the app as there is no way to seed data from the frontend if it doesn't already exist***.

```bash
cd backend
uv run python app/seed.py
```

### 4. Ingest Invoice PDFs
***NOTE: If database is cleared this will need to be ran after seeding data (seen above) as there is no way to classify invoices from the front end.***
```bash
uv run python app/ingest.py
```

### 5. Classify Line Items with AI
***NOTE: If database is cleared this will need to be ran after ingesting invoices (seen above) as there is no way to classify invoices from the front end. You will also need an Anthropic API key and an account with API useage credits to spare***.
```bash
uv run python app/classify.py
```

This calls the Claude Haiku API to assign a GL code to each unclassified line item.

### 6. Start the Backend API

```bash
uv run uvicorn app.main:app --port 8000 --reload
```

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

### 7. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Architecture and Design Decisions

### Front End

**React**
- Component-based structure 

**Recharts** 
- Built on top of React and modularizes key chart types needed for the dashboard display of this platform (e.g., bar chart, pie graph, tables)
---
### Back End

**FastAPI (Python)**
- Async API request handling for high-traffic loads for when the platform scales
- Integration with SQLModel
- Built to use Python's familiar OOP structure and allow for the use of PDF parsing libraries like pdfplumber
---
### Database

**SQLite** 
- Relational database that I'm familiar with. Simple to set up locally.

**SQLModel** 
- Models database schemas and allows for type-safe data retrieval and insertion of invoice and line item data through its type validation features.

--- 
### PDF Parsing

**pdfplumber**
- Layout-aware data extraction from PDFs that can be leveraged in this case since only Amazon Business Invoices (common layout) are being parsed.

--- 
### GL Classification
--- 
**Claude AI (haiku-4-5)** 
- Fast and relatively cost-efficient for semantic understanding and General Ledger account classification. Also have a Claude Pro membership and was given a free $5 credit for API usage.

--- 
### Package Management

**uv (Python)** 
- Simplified Python package management and environment features for the backend.

**npm (JavaScript)** 
- Simplified JavaScript package management and environment features for the frontend.

---

## Assumptions Made About the Data or Problem

**What should be done if a general ledger code cannot be confidently assigned to a line item?**

Manual action must be taken on the unclassified line items missing a GL code for appropriate accounting.

**Do all users of the platform need to be able to view all company data?**

Levels of access should be assigned based on the property code of a user and/or role (e.g., administrator status).

**What is to be done with GL codes found in the GL List.xlsx file with no description?**

They are to be ignored as there is no semantic understanding that can be associated with those GL codes through AI or human review. There are 2 known codes with no description (6372 and 7654).

**Is there any action that needs to be taken on invoices that don't have a property code listed or do not match a known code?**

Those invoices should be submitted for review and will not have their line items classified until a valid property code is given to link the purchases to.

**What should be used to calculate total spend?**

All line items that have been classified to a GL code are individually summed without tax and promotions/discounts included to give an accurate total cost of classified items. Further research and time will be needed to include costs with tax and discounts/promotions on a CLASSIFIED per line item basis.

---

## Known Limitations
**Line item to general ledger account classification confidence is not stable or verifiable.**
**PDF extraction is only tailored to Amazon Business Invoices.**
**Unable to upload invoice PDF files from the front end to be classified.**
**Processing 100 invoices takes upwards of 10 minutes as the Claude (haiku-4-5) API is set up to be synchronous on the platform.**
**Unable to write corrections to the database for invoices and line items needing review. There is also no role management established for who can and cannot edit that data.**
**No accounting on the dashboard for taxes and discounts/promotions on invoices and line items**

---

## What I'd Build or Change if This Were Going to Production, or if I Had More Time

### Improve GL Classification Reliability
- Training an open source model like Google's BERT off Monarch's data set of historical general ledger account classifications. This has multiple benefits including no licensing fees, faster processing costs as the model can be used locally and is more lightweight, better semantic understanding of purchases specific to Monarch, and, most importantly, the data being fed to the model is not going to be accessed by a 3rd party. It is worth noting that depending on the size of the data set, the cost of researching training methods and compute usage could be relatively important.

### Support Multiple Invoice Formats
- If there were only a concrete set of possible invoice templates confirmed by the property teams, I would stick to adjusting the backend ingest.py file to handle those specific templates. If not, I would look more into using vision language models like Claude 3.5 vision to handle variable invoice formats. This would come at a cost with model usage.

### Invoice Upload from the Front End
- I would create a PDF file or zip folder upload FastAPI endpoint that would handle PDF files passed to it from a front end user session.

### Async Classification Pipeline
- I would implement a Redis queue, Python Celery background workers, and AsyncAnthropic to reduce server idle time and speed up general ledger classification time. How it works is FastAPI will create a task for a batch of ingested invoices and insert that task in a Redis queue where a Celery worker (background process) is waiting to pull from. Once the task is pulled by a background Celery worker, that worker can utilize the Claude API's async feature to send off multiple requests in a short amount of time. As the classifications come in, the front end can be polling the database for new classifications until the worker completes. I'm currently implementing similar functionality in a personal project.

### Review Queue Editing and Role Management
- I already have JWT authentication set up to isolate dashboard views depending on different roles. In a real-world scenario, I would reach out to stakeholders and confirm what role should be able to edit data that is labeled for review. More research would need to be done on restricting edits and having backup plans for if data is input incorrectly. Implementing an audit trail of sorts to track who updated reviewable items (and potentially approved those updates) could be utilized here.

### Tax and Discount Accounting
- A Weighted Tax Distribution calculation would need to be established. Since the tax amount is at the header of the invoice, the calculation should proportionally allocate tax to each line item based on its percentage of the subtotal. Discounts could be handled the same way. I would just need to ensure that discounts are applicable to all items in the invoice vs geared for a specific item in which case that discount would only be applied to that individual item and included in the sum once that item is classified.

### Database move from SQLite to PostgreSQL
- I would change the current database from a SQLite implementation to a PostgreSQL implementation as PostgreSQL is useful at handling concurrency and provides row-level locking when there are multiple updates to the same record.
