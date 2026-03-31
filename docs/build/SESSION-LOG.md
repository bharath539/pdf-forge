# PDF Forge — Session Log

## Session 1 — 2026-03-31

### What happened
- Drafted full architecture document and privacy guarantees
- Created 21-task implementation plan across 8 phases
- Built the entire V1 application in a single session (20/21 tasks)

### Phase-by-phase execution

**Phase 1 — Foundation (T1, T2, T21)**
- Scaffolded FastAPI backend with routers, services, models, DB stubs
- Scaffolded Next.js 14 frontend with App Router, Tailwind, all page shells
- Created GitHub repo: https://github.com/bharath539/pdf-forge
- Created docker-compose.yml for local Postgres
- Created CLAUDE.md for future session handoff

**Phase 2 — Backend Core (T3, T4)**
- SQL migration: format_schemas + generation_log tables with UUID PKs, JSONB, triggers
- DB connection module with asyncpg pool + migration runner
- Full Pydantic models: FormatSchema (13 sub-models), GenerationParams (12 scenarios), API request/response models

**Phase 3 — Format Learning Pipeline (T5, T6, T7, T10)**
- FormatLearner: 7-step extraction (page layout, fonts, sections, table analysis, pattern detection, page breaks, assembly)
- SchemaSanitizer: 10 PII regex patterns, allowlist for format patterns/hex colors/font names, recursive dict walker
- DataFaker/TransactionFaker: bimodal amount distribution, 40+ merchants, weekday-weighted dates, seed reproducibility

**Phase 4+5+6 — API Layer + Generator (T8, T9, T11-T14)**
- POST /api/learn: multipart upload → learn → sanitize → save, BytesIO zeroed in finally block
- CRUD /api/formats: list, detail, update, delete with proper 404s
- SyntheticGenerator: reportlab-based PDF rendering with pixel-accurate layout from schema
- Multi-page support, all 12 scenarios, batch zip generation
- POST /api/generate, /generate/preview, /generate/batch with StreamingResponse

**Phase 7 — Frontend Pages (T15, T16, T17)**
- Upload Portal: 4-state flow (upload → processing → preview → saved), privacy callout, SchemaPreview component
- Format Library: responsive grid, skeleton loading, detail slide-out panel, delete confirmation modal
- Generation Console: 2-column layout, 12 scenario cards, ScenarioBuilder with dynamic params, download/preview/batch

**Phase 8 — Quality (T18, T19)**
- 76+ tests: sanitizer (33), data faker (26), generator (17), health (1)
- GitHub Actions CI: backend lint (ruff) + test (pytest with Postgres), frontend build (tsc + lint + build)
- Auto-labeler for PRs

### Files created (key files)
```
backend/
  app/main.py, config.py
  app/routers/health.py, learn.py, formats.py, generate.py
  app/services/format_learner.py, schema_sanitizer.py, synthetic_generator.py, data_faker.py
  app/models/schema.py, generation.py
  app/db/connection.py, migrations/001_initial.sql
  tests/conftest.py, test_sanitizer.py, test_data_faker.py, test_generator.py, test_health.py
  requirements.txt, requirements-dev.txt, pyproject.toml

frontend/
  src/app/layout.tsx, page.tsx
  src/app/upload/page.tsx, formats/page.tsx, generate/page.tsx
  src/components/UploadDropzone.tsx, FormatCard.tsx, SchemaPreview.tsx, ScenarioBuilder.tsx
  src/lib/api-client.ts

docs/
  architecture/ARCHITECTURE.md
  PRIVACY.md
  build/PROGRESS.md, SESSION-LOG.md

docker-compose.yml, CLAUDE.md, .github/workflows/ci.yml
```

### Key decisions
- Separate repo from Keel Money — privacy boundary + different lifecycle
- In-memory only PDF processing with sanitizer safety net
- asyncpg for DB, reportlab for PDF generation, pdfplumber for parsing
- 12 test scenarios covering realistic bank statement variations
- Schema stores structural metadata only — no PII, no transaction data

### Remaining
- T20: Deploy (Vercel frontend + Railway/Fly.io backend) — manual step
- Initial commit + push to GitHub
