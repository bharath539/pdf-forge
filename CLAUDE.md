# PDF Forge — Claude Code Instructions

> **Start every session by reading docs/build/PROGRESS.md and docs/build/SESSION-LOG.md.**
> **Update both after completing tasks.**

## Project
PDF Forge learns bank PDF statement formats and generates synthetic PDFs for testing.
Separate project from Keel Money — serves as a test data generator for the PDF import pipeline.

## Tech Stack
- **Frontend:** Next.js 14 (App Router), Tailwind CSS — in `frontend/`
- **Backend:** FastAPI (Python 3.11+) — in `backend/`
- **PDF Parsing:** pdfplumber, pdfminer.six
- **PDF Generation:** reportlab
- **Database:** PostgreSQL 16 (format schemas only, no user data)

## Architecture
Read `docs/architecture/ARCHITECTURE.md` for full system design.

## Privacy (CRITICAL)
- Uploaded PDFs are processed in-memory ONLY — never written to disk
- Only format schemas (structural metadata) are stored — never transaction data or PII
- Schema sanitizer must run on every learned schema before storage
- See `docs/PRIVACY.md` for full guarantees

## Development
```bash
# Backend
cd backend && source venv/bin/activate && uvicorn app.main:app --reload

# Frontend
cd frontend && npm run dev

# Database
docker-compose up -d
```

## Git
- Work on `main` branch
- Run tests before committing: `cd backend && pytest` and `cd frontend && npm run build`

## Session Handoff
- `docs/build/PROGRESS.md` — task status table
- `docs/build/SESSION-LOG.md` — what happened each session, files changed, decisions made
- Update BOTH at end of every session
