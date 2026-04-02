# V3 Plan: Redacted PDF as Template

## Context
The V2 template pipeline extracts elements and rebuilds PDFs from scratch (reportlab) or overlays on the original PDF (PyMuPDF). The reportlab approach produces low-fidelity output. The overlay approach needs the original PDF at generation time, which violates the privacy constraint (original PDFs are never stored).

**Solution:** During learn, use PyMuPDF to create a **redacted copy** of the original PDF (all PII/data fields whited out). Store the redacted PDF bytes + element metadata. During generation, open the stored redacted PDF and overlay fake data at the recorded positions. This gives pixel-perfect fidelity AND privacy.

## Pipeline Flow

```
LEARN (has original PDF):
  Extract (pdfplumber) → Classify (data vs structural) → Redact (PyMuPDF white-out)
  → Sanitize (metadata placeholders) → Store (redacted PDF bytes + metadata JSON)

GENERATE (no original PDF needed):
  Fetch redacted PDF + metadata from DB → Generate fake data → Overlay at stored positions → Return PDF
```

## Implementation (11 tasks)

### T1: Add PyMuPDF dependency
**File:** `backend/requirements.txt`
- Add `PyMuPDF>=1.23.0` (already imported in overlay_renderer.py but not listed)

### T2: DB migration — add redacted_pdf column
**New file:** `backend/app/db/migrations/003_add_redacted_pdf.sql`
```sql
ALTER TABLE pdf_templates ADD COLUMN IF NOT EXISTS redacted_pdf BYTEA;
ALTER TABLE pdf_templates ADD COLUMN IF NOT EXISTS template_version TEXT NOT NULL DEFAULT 'v2';
```
Existing V2 rows keep `redacted_pdf=NULL, template_version='v2'`. New V3 rows get the redacted bytes.

### T3: Update PDFTemplate model — add RedactedRect
**File:** `backend/app/models/template.py`
- New `RedactedRect` model: `page, x0, y0, x1, y1, element_index` — records exact bbox found by `search_for()` during redaction
- Add `redacted_rects: list[RedactedRect]` to `PDFTemplate`
- Add `template_version` to `PDFTemplateRecord`

### T4: Extract shared PyMuPDF helpers
**New file:** `backend/app/services/pdf_helpers.py`
- Extract from `overlay_renderer.py`: `_hex_to_rgb()`, `_closest_rect()`, `_detect_account_digits()`, `_insert_text()`, `_format_amount()`, `_format_date_*()` helpers
- Update `overlay_renderer.py` to import from shared module
- Avoids duplication between redactor and renderer

### T5: Create PDF Redactor service
**New file:** `backend/app/services/pdf_redactor.py`
- `PDFRedactor.redact(pdf_bytes, template) -> (redacted_bytes, list[RedactedRect])`
- For each DATA_PLACEHOLDER element (with original text still intact, BEFORE sanitization):
  - `page.search_for(original_text)` → find exact rect
  - `page.add_redact_annot(rect, fill=(1,1,1))` → white out
  - Record the found rect as `RedactedRect`
  - Fallback: use pdfplumber coordinates if search fails
- Also redact embedded account number digits
- `page.apply_redactions()` per page
- Return redacted PDF bytes + rects
- **CRITICAL: Must run BEFORE sanitizer** (sanitizer replaces text with "{amount}" which breaks search)

**Reuse from overlay_renderer.py:**
- `_closest_rect()` (lines 302-311) — find nearest rect to expected position
- `_detect_account_digits()` (lines 157-172) — regex for embedded account numbers
- PyMuPDF APIs: `page.search_for()`, `page.add_redact_annot()`, `page.apply_redactions()`

### T6: Create Redacted PDF Renderer
**New file:** `backend/app/services/redacted_renderer.py`
- `RedactedRenderer.render(redacted_pdf_bytes, template, params) -> BytesIO`
- Open stored redacted PDF with `fitz.open(stream=bytes)`
- For each data element that has a RedactedRect:
  - Generate fake value (amount/date/name/description)
  - Calculate font size from rect height: `fontsize = (y1-y0) * 0.88`
  - Calculate baseline: `baseline_y = y0 + (y1-y0) * 0.82`
  - `page.insert_text(Point(x0, baseline_y), fake_text, fontname, fontsize, color)`
- No `search_for()` needed at generation time — positions are pre-recorded
- Transaction count: cap at template row count (fewer = leave blanks, more = cap)
- Also add `render_preview` (page 0 only) and `render_batch` (zip)

**Reuse from overlay_renderer.py:**
- `_insert_text()` (lines 174-199) — font fallback logic
- `_generate_non_row_values()`, `_generate_row_values()` — fake data mapping
- `_hex_to_rgb()` (lines 44-54) — color conversion
- `TransactionFaker` from data_faker.py — completely as-is

### T7: Update Learn Router
**File:** `backend/app/routers/learn.py`
- After classify, BEFORE sanitize: call `PDFRedactor.redact(original_bytes, template)`
- Store `redacted_rects` on template
- Then sanitize (replaces text with placeholders for metadata)
- Update INSERT query: add `redacted_pdf` BYTEA and `template_version='v3'`
- Original PDF buffer still zeroed in finally block (privacy preserved)

**Sequence:**
```
1. content = await file.read()
2. pdf_buffer = BytesIO(content)
3. template = extractor.extract(pdf_buffer)
4. template = classifier.classify(template)
5. redacted_bytes, rects = redactor.redact(content, template)  ← NEW (needs original bytes)
6. template.redacted_rects = rects                              ← NEW
7. template = sanitizer.sanitize(template)                      ← existing (safe to run after redaction)
8. # Zero pdf_buffer in finally block                           ← existing
9. # Save template JSON + redacted_bytes to DB                  ← updated
```

### T8: Update Generate Router
**File:** `backend/app/routers/generate.py`
- Fetch `redacted_pdf, template_version` alongside `template_json` from DB
- If `template_version='v3'` and `redacted_pdf` exists → use `RedactedRenderer`
- If `template_version='v2'` → use existing `TemplateRenderer` (backward compat)
- V1 fallback unchanged

### T9: Update Formats Router
**File:** `backend/app/routers/formats.py`
- Add `template_version` to list/detail responses
- Update SELECT queries to include the new column

### T10: Update test_local_pipeline.py
**File:** `backend/test_local_pipeline.py`
- Add V3 path: extract → classify → redact → sanitize → render from redacted PDF
- Print redacted PDF size, rect count
- Save both redacted template PDF and final synthetic PDF for inspection

### T11: Unit tests
**New files:** `backend/tests/test_pdf_redactor.py`, `backend/tests/test_redacted_renderer.py`
- Redaction produces valid PDF with no PII text
- Redacted rects count matches data element count
- Round-trip: redact → render produces valid PDF
- Different seeds produce different outputs

## Implementation Order
```
T1 (requirements) → T2 (migration) → T3 (models) → T4 (helpers)
→ T5 (redactor) → T6 (renderer) → T7 (learn API) → T8 (generate API)
→ T9 (formats API) → T10 (test script) → T11 (unit tests)
```

## What's Reused As-Is (NO changes needed)
| File | Purpose |
|------|---------|
| `template_extractor.py` | Extract all elements from PDF |
| `data_classifier.py` | Classify elements as structural/data |
| `template_sanitizer.py` | Replace data text with placeholders |
| `data_faker.py` | Generate fake transactions/amounts |
| All V1 code | Backward compatibility |

## New Files
| File | Purpose |
|------|---------|
| `services/pdf_redactor.py` | White out PII in original PDF during learn |
| `services/redacted_renderer.py` | Overlay fake data on stored redacted PDF |
| `services/pdf_helpers.py` | Shared PyMuPDF helper functions |
| `db/migrations/003_add_redacted_pdf.sql` | Add BYTEA column for redacted PDF |
| `tests/test_pdf_redactor.py` | Redactor unit tests |
| `tests/test_redacted_renderer.py` | Renderer unit tests |

## Modified Files
| File | Change |
|------|--------|
| `requirements.txt` | Add PyMuPDF |
| `models/template.py` | Add RedactedRect model |
| `routers/learn.py` | Add redaction step, store PDF bytes |
| `routers/generate.py` | Branch on template_version for V3 renderer |
| `routers/formats.py` | Include template_version in responses |
| `overlay_renderer.py` | Extract helpers to shared module |
| `test_local_pipeline.py` | Add V3 pipeline path |

## Privacy Verification
- Original PDF: read in memory, used for extraction + redaction, then zeroed
- Stored redacted PDF: all data fields whited out, no PII remains
- Template JSON: contains only placeholders ("{amount}", "{date}", etc.)
- RedactedRects: only bounding box coordinates (numbers), no text
- At no point is the original PDF written to disk or stored unredacted

## Known Limitations
- Transaction count capped at template row count (can't dynamically add rows to a redacted PDF)
- Fonts: PyMuPDF uses Helvetica/Helvetica-Bold fallback (original fonts not embeddable)
- Redacted PDF size: 500KB-2MB stored in DB (acceptable for PostgreSQL BYTEA)
- Fewer transactions than template = some rows left blank (white space)

## Verification Plan
1. Run `test_local_pipeline.py` against Wells Fargo + Chase + Citi PDFs
2. Visual comparison: synthetic should be near-identical to original (different data, same layout)
3. Verify redacted PDF has no PII: search for known names/amounts in stored bytes
4. Run `pytest backend/tests/` for regressions
5. Deploy to Railway, test via frontend upload at Vercel URL
