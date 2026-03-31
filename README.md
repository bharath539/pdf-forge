# PDF Forge

> Learn real bank statement formats. Generate unlimited synthetic PDFs. Never store user data.

PDF Forge is a developer tool for creating realistic synthetic bank statement PDFs. Upload a real statement to teach the system the format, then generate as many synthetic copies as you need — with full control over scenarios like multi-month, multi-account, partial periods, and edge cases.

**Built for testing PDF import pipelines.** Zero real data retained.

## How It Works

1. **Upload** a real bank statement PDF
2. **Learn** — the system extracts the structural format (layout, fonts, columns, patterns)
3. **Discard** — the original PDF is processed in memory and never stored
4. **Generate** — create synthetic PDFs matching that exact format with realistic fake data

## Privacy

Your data is never stored. See [PRIVACY.md](docs/PRIVACY.md) for architectural guarantees.

## Tech Stack

- **Frontend:** Next.js 14, Tailwind CSS
- **Backend:** FastAPI (Python 3.11+)
- **PDF Parsing:** pdfplumber, pdfminer.six
- **PDF Generation:** reportlab
- **Database:** PostgreSQL (format schemas only)

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11+
- PostgreSQL 15+

### Setup

```bash
# Clone
git clone https://github.com/<your-org>/pdf-forge.git
cd pdf-forge

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Architecture

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for full details.

## Test Scenarios

| Scenario | Description |
|---|---|
| `single_month` | Standard single statement |
| `multi_month` | Consecutive monthly statements |
| `multi_account` | Multiple account types from same bank |
| `partial` | Mid-cycle / incomplete period |
| `past_months` | Backdated historical statements |
| `high_volume` | Hundreds of transactions (stress test) |
| `minimal` | Single transaction |
| `zero_balance` | $0 opening and closing |
| `multi_page` | Forces page breaks across 3+ pages |

## License

MIT
