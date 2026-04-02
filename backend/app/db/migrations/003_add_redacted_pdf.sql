-- V3: Store redacted PDF bytes alongside template metadata
-- Redacted PDFs have all PII whited out — safe to store.

ALTER TABLE pdf_templates
    ADD COLUMN IF NOT EXISTS redacted_pdf BYTEA;

ALTER TABLE pdf_templates
    ADD COLUMN IF NOT EXISTS template_version TEXT NOT NULL DEFAULT 'v2';
