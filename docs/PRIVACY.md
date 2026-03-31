# PDF Forge — Privacy Guarantees

## What happens when you upload a PDF

1. Your PDF is read directly into memory. It is **never saved to disk**.
2. Our format learner extracts only the **structural layout** — page size, fonts, column positions, section ordering, date/amount format patterns.
3. A sanitizer pass scrubs the extracted schema of any string that could contain personal data.
4. The in-memory PDF buffer is zeroed and discarded.
5. The only thing stored is the **format schema** — a JSON description of how the PDF looks, with zero real data.

## What we store

- Page dimensions and margins
- Font families, sizes, and colors
- Table column positions and header labels
- Date format patterns (e.g., "MM/DD/YYYY")
- Amount format patterns (e.g., "$#,##0.00")
- Section layout (header, summary, transactions, footer)
- Description structure patterns (e.g., "DEBIT CARD PURCHASE - {merchant} {city} {state}")

## What we NEVER store

- Transaction amounts, dates, or descriptions
- Account numbers (full or partial)
- Names, addresses, or any personal information
- Balance figures
- The original PDF file or any copy of it
- Content hashes or fingerprints of the original file

## Architectural enforcement

These guarantees are not just policy — they are enforced in code:

- **No temp files.** PDF processing happens entirely in memory (`BytesIO` buffers).
- **No PII columns.** The database schema has no tables or columns that could hold personal data.
- **Sanitizer safety net.** Even if the format learner accidentally captures a data value, the sanitizer strips any string matching PII patterns (numbers that look like account numbers, SSNs, phone numbers, emails) before storage.
- **Audit trail.** Each upload logs only: timestamp, file size in bytes, and the format schema ID produced. No filename, no content hash.

## Open source

This tool is open source. You can audit the code yourself to verify these guarantees.
