# PDF Forge — Architecture

> Learn real bank statement formats. Generate unlimited synthetic PDFs. Never store user data.

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Upload   │  │Format Library│  │  Generation Console    │ │
│  │  Portal   │  │  Browser     │  │  (scenario builder)    │ │
│  └────┬─────┘  └──────┬───────┘  └───────────┬────────────┘ │
│       │               │                      │               │
└───────┼───────────────┼──────────────────────┼───────────────┘
        │               │                      │
        ▼               ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI / Python)                 │
│                                                              │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Format   │  │   Schema     │  │  Synthetic Generator   │ │
│  │  Learner  │  │   Store      │  │  (reportlab)           │ │
│  │(pdfplumber│  │  (Postgres)  │  │                        │ │
│  └──────────┘  └──────────────┘  └────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 2. Core Components

### 2.1 Format Learner (Python)

Parses an uploaded PDF **in memory** and extracts a structural format schema.

**What it captures (FORMAT — stored):**
- Page dimensions, margins, orientation
- Font families, sizes, weights, colors at each position
- Table grid: column x-positions, header row y-position, row height/spacing
- Section ordering (header → account summary → transactions → footer)
- Date format patterns (e.g., `MM/DD/YYYY`, `DD Mon YYYY`)
- Amount format patterns (e.g., `$1,234.56`, `1234.56-` for debits)
- Description field structure (max length, line-wrap behavior, indentation)
- Logo/image bounding boxes (position + dimensions only, not the image pixels)
- Line rules, borders, background fills (coordinates + colors)
- Page break patterns (how transactions split across pages)
- Statement metadata field positions (account number, period, balances)

**What it discards (DATA — never stored):**
- Actual transaction descriptions, amounts, dates
- Account numbers, names, addresses
- Balance figures
- Any PII or financial data

**Libraries:** `pdfplumber` for extraction, `pdfminer.six` as fallback parser.

### 2.2 Format Schema (JSON)

Each learned format is stored as a JSON document:

```jsonc
{
  "schema_version": "1.0",
  "bank_name": "Chase",
  "account_type": "checking",        // checking | savings | credit_card
  "display_name": "Chase Checking",
  "created_at": "2026-03-31T...",
  "created_by": "user-upload",       // or "manual"

  "page": {
    "width": 612,                     // points (8.5" x 11")
    "height": 792,
    "margins": { "top": 72, "right": 54, "bottom": 72, "left": 54 }
  },

  "fonts": [
    { "role": "header", "family": "Helvetica", "size": 14, "weight": "bold", "color": "#003366" },
    { "role": "body", "family": "Courier", "size": 9, "weight": "normal", "color": "#000000" },
    { "role": "footer", "family": "Helvetica", "size": 7, "weight": "normal", "color": "#666666" }
  ],

  "sections": [
    {
      "type": "header",
      "y_start": 72,
      "y_end": 140,
      "elements": [
        { "type": "logo_placeholder", "bbox": [54, 72, 180, 110] },
        { "type": "text_field", "role": "bank_name", "bbox": [200, 75, 400, 95], "font_ref": "header" },
        { "type": "text_field", "role": "statement_period", "bbox": [400, 75, 558, 95], "font_ref": "body" }
      ]
    },
    {
      "type": "account_summary",
      "y_start": 150,
      "y_end": 220,
      "fields": [
        { "role": "account_number_masked", "label": "Account Number", "format": "XXXX-XXXX-{4digits}" },
        { "role": "opening_balance", "label": "Beginning Balance", "format": "$#,##0.00" },
        { "role": "closing_balance", "label": "Ending Balance", "format": "$#,##0.00" }
      ]
    },
    {
      "type": "transaction_table",
      "y_start": 230,
      "columns": [
        { "header": "Date", "x_start": 54, "x_end": 120, "format": "MM/DD" },
        { "header": "Description", "x_start": 120, "x_end": 380, "format": "text", "max_chars": 45 },
        { "header": "Amount", "x_start": 380, "x_end": 460, "format": "$#,##0.00" },
        { "header": "Balance", "x_start": 460, "x_end": 558, "format": "$#,##0.00" }
      ],
      "row_height": 14,
      "alternate_row_fill": "#F5F5F5",
      "header_underline": true
    },
    {
      "type": "footer",
      "y_start": -50,                // relative to page bottom
      "elements": [
        { "type": "text_field", "role": "page_number", "format": "Page {n} of {total}" },
        { "type": "text_field", "role": "disclaimer", "max_lines": 2 }
      ]
    }
  ],

  "page_break_rules": {
    "min_rows_before_break": 3,
    "continuation_header": true,     // re-print column headers on new pages
    "orphan_control": true
  },

  "description_patterns": [
    { "category": "debit_card", "pattern": "DEBIT CARD PURCHASE - {merchant} {city} {state}" },
    { "category": "ach", "pattern": "ACH {direction} {originator}" },
    { "category": "check", "pattern": "CHECK #{number}" },
    { "category": "transfer", "pattern": "ONLINE TRANSFER {direction} {account_ref}" },
    { "category": "atm", "pattern": "ATM {action} - {location}" }
  ]
}
```

### 2.3 Synthetic Generator (Python)

Takes a format schema + generation parameters and produces a PDF.

**Generation Parameters:**

```jsonc
{
  "schema_id": "chase_checking",
  "scenario": "multi_month",         // see §3 for all scenarios
  "months": 3,                       // for multi_month
  "start_date": "2025-01-01",
  "transactions_per_month": { "min": 15, "max": 45 },
  "opening_balance": "5234.50",
  "include_edge_cases": true,        // very long descriptions, round amounts, etc.
  "seed": 42                         // reproducible output
}
```

**Library:** `reportlab` for PDF generation (pixel-level control over layout).

**Data generation:** `faker` for merchant names, addresses. Custom generators for realistic transaction amounts (bimodal distribution — many small purchases, occasional large ones).

### 2.4 Schema Store (PostgreSQL)

Minimal schema — this is a tool, not a product:

```sql
CREATE TABLE format_schemas (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_name     TEXT NOT NULL,
    account_type  TEXT NOT NULL CHECK (account_type IN ('checking', 'savings', 'credit_card')),
    display_name  TEXT NOT NULL,
    schema_json   JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(bank_name, account_type)
);

CREATE TABLE generation_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_id     UUID REFERENCES format_schemas(id),
    scenario      TEXT NOT NULL,
    parameters    JSONB NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);
-- No user data tables. No PII. Ever.
```

### 2.5 Frontend (Next.js)

Three pages:

**Upload Portal (`/upload`)**
- Drag-and-drop PDF upload
- Real-time progress: "Parsing... Extracting layout... Learning format..."
- Preview panel showing detected structure (wireframe render, no real data)
- Confirmation: "We learned the format. Your data has been discarded."
- Name the format (bank + account type) → save

**Format Library (`/formats`)**
- Grid of saved format schemas
- Each card shows: bank name, account type, date learned, section count
- Click to view full schema details
- Edit/delete capabilities

**Generation Console (`/generate`)**
- Select format(s) from library
- Choose scenario (see §3)
- Configure parameters (date range, tx count, balance range)
- Generate → download PDF(s) as zip
- Preview first page before downloading

## 3. Test Scenarios

| Scenario | Description | Parameters |
|---|---|---|
| `single_month` | Standard single statement | month, tx_count |
| `multi_month` | Consecutive monthly statements | month_count, start_date |
| `multi_account` | Multiple account types, same bank | account_types[] |
| `partial` | Mid-cycle / incomplete period | start_date, end_date (partial month) |
| `past_months` | Backdated historical statements | year, months[] |
| `high_volume` | Stress test — hundreds of transactions | tx_count (200-500+) |
| `minimal` | Single transaction, edge case | — |
| `zero_balance` | Statement with $0 opening and closing | — |
| `negative_balance` | Overdraft / credit balance scenarios | — |
| `multi_page` | Forces page breaks | tx_count (enough to span 3+ pages) |
| `mixed_types` | Debits, credits, checks, ACH, transfers | type_distribution |
| `international` | Foreign currency transactions | currencies[] |

## 4. API Endpoints

### Format Learning
```
POST   /api/learn              Upload PDF → extract and store format schema
GET    /api/formats             List all saved format schemas
GET    /api/formats/{id}        Get a specific format schema
PUT    /api/formats/{id}        Update schema metadata (name, etc.)
DELETE /api/formats/{id}        Delete a format schema
```

### Synthetic Generation
```
POST   /api/generate            Generate synthetic PDF(s) from schema + params
POST   /api/generate/preview    Generate first-page preview (PNG) before full PDF
POST   /api/generate/batch      Generate multiple scenarios in one request → zip
```

### Health
```
GET    /api/health              Service health check
```

## 5. Privacy Guarantees (Architectural)

These are enforced at the code level, not just by policy:

1. **No filesystem writes during learning.** The uploaded PDF is read from the request body into a `BytesIO` buffer. `pdfplumber` operates on this buffer. The buffer is explicitly zeroed and dereferenced after extraction.

2. **Schema sanitization pass.** After the format learner produces a schema, a dedicated sanitizer function walks the JSON tree and strips any string value longer than 50 characters or any string that matches PII patterns (SSN, account number, email, phone, address). This is a safety net — the learner shouldn't extract data, but the sanitizer catches leaks.

3. **No database columns for user data.** The schema has no tables or columns that could hold PII. There is nowhere to accidentally store it.

4. **Upload audit log.** Each upload records: timestamp, file size, schema_id produced. No filename, no content hash, nothing traceable to the source document.

5. **Memory-only processing.** The Python process handling the upload never writes temp files. `reportlab` generates output PDFs to `BytesIO`, streamed directly to the HTTP response.

## 6. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | Next.js 14 (App Router) | Fast to build, good DX, handles file uploads well |
| Styling | Tailwind CSS | Rapid UI development |
| Backend | FastAPI (Python 3.11+) | Async, fast, great for file processing APIs |
| PDF Parsing | pdfplumber + pdfminer.six | Best Python PDF extraction libraries |
| PDF Generation | reportlab | Pixel-level PDF layout control |
| Fake Data | faker | Realistic merchant names, addresses |
| Database | PostgreSQL (via Supabase or local) | JSONB support for schema storage |
| Deployment | Vercel (frontend) + Railway/Fly.io (backend) | Simple, cheap for a dev tool |

## 7. Project Structure

```
pdf-forge/
├── frontend/                    # Next.js app
│   ├── app/
│   │   ├── page.tsx             # Landing / upload
│   │   ├── formats/
│   │   │   └── page.tsx         # Format library
│   │   ├── generate/
│   │   │   └── page.tsx         # Generation console
│   │   └── api/                 # Next.js API routes (proxy to backend)
│   ├── components/
│   │   ├── UploadDropzone.tsx
│   │   ├── FormatCard.tsx
│   │   ├── SchemaPreview.tsx
│   │   ├── ScenarioBuilder.tsx
│   │   └── PdfPreview.tsx
│   └── lib/
│       └── api-client.ts        # Typed fetch wrapper
│
├── backend/                     # FastAPI app
│   ├── app/
│   │   ├── main.py              # FastAPI app + CORS
│   │   ├── routers/
│   │   │   ├── learn.py         # POST /api/learn
│   │   │   ├── formats.py       # CRUD /api/formats
│   │   │   └── generate.py      # POST /api/generate
│   │   ├── services/
│   │   │   ├── format_learner.py    # PDF → format schema extraction
│   │   │   ├── schema_sanitizer.py  # Strip any leaked PII from schema
│   │   │   ├── synthetic_generator.py # Schema + params → PDF
│   │   │   └── data_faker.py        # Realistic transaction data generation
│   │   ├── models/
│   │   │   ├── schema.py        # Pydantic models for format schema
│   │   │   └── generation.py    # Pydantic models for generation params
│   │   └── db/
│   │       ├── connection.py    # DB connection pool
│   │       └── migrations/      # SQL migrations
│   ├── tests/
│   │   ├── test_learner.py
│   │   ├── test_sanitizer.py
│   │   └── test_generator.py
│   └── requirements.txt
│
├── docs/
│   ├── architecture/
│   │   └── ARCHITECTURE.md      # This file
│   └── PRIVACY.md               # User-facing privacy guarantees
│
├── docker-compose.yml           # Local dev: backend + postgres
├── .github/
│   └── workflows/
│       └── ci.yml               # Lint + test
└── README.md
```

## 8. V1 Milestones

1. **M1 — Format Learner** — Upload a Chase checking PDF → get a valid format schema JSON
2. **M2 — Synthetic Generator** — Feed schema → get a synthetic PDF that visually matches the original layout
3. **M3 — Frontend Upload** — Drag-and-drop UI with format preview and save
4. **M4 — Generation Console** — Select format, pick scenario, download synthetic PDF
5. **M5 — Multi-scenario batch** — Generate a zip of PDFs covering all test scenarios for a given format
6. **M6 — Deploy** — Frontend on Vercel, backend on Railway/Fly.io
