# PDF Forge V2 — Template-Based Rewrite Plan

## Problem Statement

The current architecture extracts an abstract "format schema" from PDFs (sections, table columns, fonts) then rebuilds PDFs from scratch using reportlab. This produces synthetic PDFs that look nothing like the original — it only reproduces a simplified transaction table and header, losing all the rich formatting, fine print, payment coupons, warning tables, interest calculations, section groupings, and visual design of the original statement.

**The fix:** Instead of abstracting and reconstructing, we should **clone the PDF and replace only the data fields** with fake values. Every text element, every line, every box should be preserved exactly — only names, amounts, dates, account numbers, and transaction descriptions get swapped.

## New Architecture

### Current Flow (V1 — lossy reconstruction)
```
Upload PDF → Extract abstract schema → Discard PDF → Rebuild from scratch with fake data
```

### New Flow (V2 — template-based cloning)
```
Upload PDF → Extract ALL elements with positions → Classify each as structural/data
→ Store template (structural text kept, data fields become typed placeholders)
→ Generate: replay template, inject fake values into placeholders
```

## Key Design Principles

1. **Pixel-perfect fidelity** — Every structural element (headers, fine print, logos, lines, boxes, section bars) is preserved exactly from the original PDF
2. **Privacy preserved** — Only the template is stored, never the original PDF. All PII (names, account numbers, amounts, transaction details) are stripped and replaced with typed placeholders
3. **Data fields are typed** — Each placeholder knows its type (amount, date, name, address, account_number, transaction_description) so the faker can generate appropriate values
4. **Page-aware** — Template stores elements per-page, handles multi-page statements correctly

## Detailed Task Breakdown

### Phase 1: New Models & Template Extractor

#### T1: Define new Pydantic models for template elements
**File:** `backend/app/models/template.py` (new file)
**What to build:**
- `TextElement` — a single text item: `page`, `x`, `y`, `text`, `font_family`, `font_size`, `font_weight`, `color`, `element_type` (structural | data_placeholder), `data_type` (amount | date | name | address | account_number | description | phone | email | None)
- `LineElement` — a drawn line: `page`, `x0`, `y0`, `x1`, `y1`, `stroke_color`, `stroke_width`
- `RectElement` — a drawn rectangle: `page`, `x0`, `y0`, `x1`, `y1`, `fill_color`, `stroke_color`, `stroke_width`
- `ImageElement` — an image/logo area: `page`, `x0`, `y0`, `x1`, `y1`, `placeholder` (bool)
- `PDFTemplate` — the full template: `bank_name`, `account_type`, `page_layout` (width, height per page), `text_elements: list[TextElement]`, `line_elements: list[LineElement]`, `rect_elements: list[RectElement]`, `image_elements: list[ImageElement]`, `page_count`, `data_field_summary` (counts of each data_type for the faker)
- Keep existing `FormatSchema`, `AccountType`, `FontSpec` models for backward compatibility
- `PDFTemplateRecord` — DB record with id, bank_name, template JSON, timestamps

**Acceptance criteria:**
- All models validate with Pydantic
- Template JSON round-trips (serialize/deserialize)
- Existing models still work (no breaking changes)

---

#### T2: Build template extractor — extract ALL elements from PDF
**File:** `backend/app/services/template_extractor.py` (new file)
**What to build:**
- `TemplateExtractor.extract(pdf_buffer: BytesIO) -> PDFTemplate`
- Use pdfplumber to iterate ALL pages and extract:
  - Every character → group into words using x-gap logic (reuse `_chars_to_words`)
  - Every line (horizontal/vertical rules, borders)
  - Every rectangle (background fills, boxes, borders)
  - Every image (logo placeholders — store bbox, not image data)
- Store each element with its exact page number, position (x, y), font (family, size, weight), and color
- At this stage, ALL elements are marked as `element_type="structural"` and `text` contains the actual text from the PDF

**Reuse from V1:**
- `_chars_to_words()` logic for word grouping
- `_cluster_text_lines()` for line grouping
- `_font_family()`, `_font_weight()`, `_hex_color()` for font/color extraction
- Page layout extraction (margins, dimensions)

**Acceptance criteria:**
- Given a PDF, extracts every visible text element with correct position and font
- Extracts lines, rectangles, and image bounding boxes
- Round-trip: extracting from a PDF and rendering all structural elements should produce a visually identical PDF (minus data replacements)

---

#### T3: Build data classifier — identify which elements are PII/data
**File:** `backend/app/services/data_classifier.py` (new file)
**What to build:**
- `DataClassifier.classify(template: PDFTemplate) -> PDFTemplate`
- Takes a template with all elements marked structural, returns template with data elements reclassified
- Classification rules (in priority order):
  1. **Amounts** — text matching `_AMOUNT_RE` (dollar amounts like `$1,234.56`, `-$50.00`)
  2. **Dates** — text matching date patterns (`MM/DD/YYYY`, `MM/DD/YY`, `MM/DD`, month names with dates)
  3. **Account numbers** — sequences of 4+ digits, possibly masked (`XXXX1234`, `****2917`, `4147 1814 0081 2917`)
  4. **Names** — text in the mailing address block (top portion of page, multi-line block with name + street + city/state/zip). Use positional heuristics: a block of 2-4 lines in the upper portion with a line matching `_ADDRESS_LINE_RE` (state + ZIP) → the lines above are name/street
  5. **Addresses** — lines matching street patterns (`\d+ .+ (St|Dr|Ave|Blvd|Ln|Rd|Ct|Way|Pl)`) and city/state/zip
  6. **Phone numbers** — matching phone patterns from sanitizer
  7. **Email addresses** — matching email pattern from sanitizer
  8. **Transaction descriptions** — text elements that appear in the transaction table area (between table header row and table footer/totals), in the description column position, that are NOT amounts/dates. Detect by: finding the "Description" column header, then classifying text elements at similar x-positions in subsequent rows
  9. **Transaction category labels** — "TOTAL PAYMENTS", "TOTAL PURCHASES", subtotal lines → keep as structural (they're labels, not data)
  10. **Reference numbers** — alphanumeric strings like `F353100EF00CHGDDA`, `2469216DW33A9WV2H` in the reference number column

- **Everything else stays structural** — section headers, fine print, legal text, column headers, logos, payment warnings, interest rate disclosures, etc.

**Reuse from V1:**
- `_AMOUNT_RE` regex
- `_DATE_PATTERNS` regexes
- Sanitizer PII patterns (SSN, credit card, email, phone, address)
- `_KNOWN_BANK_NAMES` for avoiding false positives
- `_ADDRESS_LINE_RE` for address detection

**Acceptance criteria:**
- Given the Wells Fargo PDF template: correctly classifies amounts, dates, names, addresses, transaction descriptions, and reference numbers as data
- Does NOT classify section headers ("Account Summary", "Transactions", "Interest Charge Calculation"), legal disclaimers, payment warnings, or column labels as data
- All elements have appropriate `data_type` set

---

#### T4: Build template sanitizer — strip PII from template before storage
**File:** Update `backend/app/services/schema_sanitizer.py` or new `template_sanitizer.py`
**What to build:**
- `TemplateSanitizer.sanitize(template: PDFTemplate) -> PDFTemplate`
- For each element classified as `data_placeholder`:
  - Replace `text` with a placeholder string: `"{amount}"`, `"{date}"`, `"{name}"`, `"{address}"`, `"{account_number}"`, `"{description}"`, `"{ref_number}"`
  - Keep position, font, size, color intact
- For structural elements: verify no PII leaked through (run existing PII regex patterns)
- Generate `data_field_summary`: count how many of each data_type exist (e.g., 35 amounts, 35 dates, 35 descriptions, 1 name, 1 address, 3 account_numbers)

**Acceptance criteria:**
- No actual PII remains in the stored template
- All data fields are typed placeholders
- Structural text is preserved verbatim
- Template is safe to store in the database

---

### Phase 2: Template-Based Generator

#### T5: Build template renderer — replay template with fake data
**File:** `backend/app/services/template_renderer.py` (new file)
**What to build:**
- `TemplateRenderer.render(template: PDFTemplate, params: GenerationParams) -> BytesIO`
- Create a reportlab Canvas with the template's page dimensions
- For each page in the template:
  - Draw all `LineElement`s (rules, borders)
  - Draw all `RectElement`s (background fills, boxes)
  - Draw all `ImageElement`s (logo placeholder rectangles)
  - Draw all `TextElement`s:
    - If `element_type == "structural"`: draw the original text at the original position with the original font/size/color
    - If `element_type == "data_placeholder"`: look up the fake value from the generated data, draw it at the original position with the original font/size/color
- Handle text fitting: if the fake value is longer/shorter than the original, truncate or pad to fit the same bounding width

**Fake data mapping:**
- Use `TransactionFaker` to generate transactions matching the template's transaction count
- Map each `{description}` placeholder to a generated transaction description (in order)
- Map each `{amount}` placeholder to the corresponding transaction amount
- Map each `{date}` placeholder to the corresponding transaction date
- Map `{name}` to a Faker-generated name
- Map `{address}` to a Faker-generated address
- Map `{account_number}` to a masked fake account number
- Map `{ref_number}` to a random alphanumeric reference

**Reuse from V1:**
- reportlab Canvas setup and font mapping (`_resolve_font`, `_FONT_MAP`)
- `_draw_text()` helper
- `_hex_to_color()` helper
- `format_amount()` and date formatting
- `TransactionFaker` (entirely as-is)
- GenerationParams and Scenario models

**Acceptance criteria:**
- Given the Wells Fargo template + fake data → output PDF is visually near-identical to original, just with different names/amounts/dates
- All structural elements (fine print, warnings, interest tables, section headers) are exactly preserved
- Multi-page templates render correctly across pages
- Text doesn't overflow or misalign

---

#### T6: Handle transaction count variation
**What to build:**
- The original PDF might have N transactions, but the generation params may request M transactions
- If M > N: the template needs to "expand" the transaction area — repeat the row template for additional rows, potentially adding pages
- If M < N: remove excess transaction row elements from the rendered output
- This requires identifying which text elements belong to the "transaction row group" — a repeating vertical pattern of (date, description, amount, balance/charges) at consistent y-intervals

**Approach:**
- During classification (T3), mark transaction row elements with a `row_index` field
- Detect the row height (y-spacing between consecutive transaction rows)
- When M != N, calculate the y-offset needed and shift all elements below the transaction area accordingly
- For page breaks: if shifted content exceeds page height, split onto new pages (carry over structural elements like headers/footers from the template's continuation pages)

**Acceptance criteria:**
- Generate a PDF with 5 transactions from a template that had 20 → shorter PDF, no blank space
- Generate a PDF with 50 transactions from a template that had 7 → multi-page, rows flow naturally
- Summary totals (if present) are recalculated to match the generated transactions

---

#### T7: Handle summary/totals recalculation
**What to build:**
- Templates with "Account Summary" sections show totals (Previous Balance, Payments, Purchases, New Balance, etc.)
- These need to be recalculated based on the generated transactions, not preserved from the template
- During classification, mark summary amount fields with specific roles (opening_balance, closing_balance, total_deposits, total_withdrawals, etc.)
- During rendering, compute actual totals from the generated transactions and inject them

**Acceptance criteria:**
- Summary section shows correct totals that match the generated transactions
- Beginning/Ending balance are consistent with transaction amounts
- "Total Payments", "Total Purchases" etc. in Wells Fargo format match transaction sub-totals

---

### Phase 3: API & Storage Updates

#### T8: Database migration for template storage
**File:** `backend/app/db/migrations/002_add_templates.sql` (new file)
**What to build:**
- New table `pdf_templates`:
  ```sql
  CREATE TABLE pdf_templates (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      bank_name TEXT NOT NULL,
      account_type TEXT NOT NULL,
      display_name TEXT NOT NULL,
      template_json JSONB NOT NULL,
      page_count INTEGER NOT NULL DEFAULT 1,
      data_field_count INTEGER NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  ```
- Keep existing `format_schemas` table for V1 backward compatibility
- Add trigger for updated_at

---

#### T9: Update learn API to use template extractor
**File:** `backend/app/routers/learn.py`
**What to change:**
- Call `TemplateExtractor.extract()` instead of `FormatLearner.learn()`
- Call `DataClassifier.classify()` to identify data fields
- Call `TemplateSanitizer.sanitize()` to strip PII
- Save to `pdf_templates` table instead of `format_schemas`
- Return updated response model with template info

---

#### T10: Update generate API to use template renderer
**File:** `backend/app/routers/generate.py`
**What to change:**
- Fetch template from `pdf_templates` table
- Call `TemplateRenderer.render()` instead of `SyntheticGenerator.generate()`
- Keep batch/preview endpoints working
- Same response format (streaming PDF blob)

---

#### T11: Update frontend for template workflow
**Files:** `frontend/src/app/upload/page.tsx`, `frontend/src/app/formats/page.tsx`, `frontend/src/app/generate/page.tsx`
**What to change:**
- Upload page: show template preview with data fields highlighted (optional enhancement)
- Format library: show template info (page count, number of data fields, bank name)
- Generate page: same interface — select template, choose scenario, download PDF
- Update API client types to match new response models

---

### Phase 4: Testing & Validation

#### T12: Unit tests for template extractor
- Test extraction from Chase checking statement → verify all text elements captured
- Test extraction from Wells Fargo credit card → verify complex layout captured
- Test extraction from Citi credit card → verify another format works
- Verify line/rect/image extraction

#### T13: Unit tests for data classifier
- Test classification on Chase → verify amounts, dates, descriptions, names correctly identified
- Test classification on Wells Fargo → verify 6-column table elements classified correctly
- Test that structural elements (fine print, section headers) are NOT classified as data
- Edge cases: masked account numbers, negative amounts, date ranges

#### T14: Integration tests — full pipeline
- Upload real PDF → extract → classify → sanitize → save → generate → compare to original
- Run against all 10 test PDFs in `keel-money/test-data/real-test-data/`
- Visual comparison: generated PDF should be near-identical to original (different data, same layout)

#### T15: Update existing tests
- Update or deprecate V1 tests that test the old FormatLearner/SyntheticGenerator
- Keep sanitizer tests (PII detection still relevant)
- Keep data_faker tests (unchanged)
- Add new tests for template models

---

## Implementation Order

```
Phase 1 (Foundation):  T1 → T2 → T3 → T4  (models, extractor, classifier, sanitizer)
Phase 2 (Generator):   T5 → T6 → T7        (renderer, row variation, totals)
Phase 3 (Integration): T8 → T9 → T10 → T11 (DB, APIs, frontend)
Phase 4 (Validation):  T12 → T13 → T14 → T15 (tests)
```

## Files Changed vs New

| File | Action |
|------|--------|
| `backend/app/models/template.py` | NEW |
| `backend/app/services/template_extractor.py` | NEW |
| `backend/app/services/data_classifier.py` | NEW |
| `backend/app/services/template_renderer.py` | NEW |
| `backend/app/services/template_sanitizer.py` | NEW (or update schema_sanitizer.py) |
| `backend/app/db/migrations/002_add_templates.sql` | NEW |
| `backend/app/routers/learn.py` | MODIFY |
| `backend/app/routers/generate.py` | MODIFY |
| `backend/app/models/schema.py` | KEEP (backward compat) |
| `backend/app/services/format_learner.py` | KEEP (V1, deprecate later) |
| `backend/app/services/synthetic_generator.py` | KEEP (V1, deprecate later) |
| `backend/app/services/data_faker.py` | KEEP (reuse as-is) |
| `frontend/src/lib/api-client.ts` | MODIFY |
| `frontend/src/app/*/page.tsx` | MODIFY |

## Files to Reuse As-Is
- `backend/app/services/data_faker.py` — fake transaction generation
- `backend/app/models/generation.py` — generation params/scenarios
- `backend/app/config.py` — settings
- `backend/app/db/connection.py` — DB pool
- `backend/app/routers/health.py` — health check

## Privacy Guarantees (Unchanged)
- Original PDF processed in-memory only — never written to disk
- Template stores ONLY structural text + typed placeholders — no PII
- Sanitizer scans template before storage to verify no PII leakage
- BytesIO buffer is zeroed after extraction (same as V1)

## Risk Notes
- **Template size** — Storing ALL text elements as JSON will be larger than V1 schemas (est. 50-200KB vs 5-10KB). JSONB in PostgreSQL handles this fine.
- **Font matching** — reportlab only has a few built-in fonts. Text rendered in proprietary fonts (e.g., Wells Fargo's custom font) will use the closest mapped family. This is the same limitation as V1.
- **Transaction count variation (T6)** — This is the hardest task. Expanding/contracting the transaction area while keeping everything else aligned requires careful y-offset calculation. Start with exact same count, then handle variation.
- **Images/logos** — We can't store actual logo images (proprietary). Logo areas will remain as gray placeholder rectangles, same as V1. A future enhancement could allow uploading logo images.
