-- V2: Template-based PDF generation
-- Stores complete PDF templates with typed placeholders instead of abstract schemas.

CREATE TABLE IF NOT EXISTS pdf_templates (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_name        TEXT NOT NULL,
    account_type     TEXT NOT NULL CHECK (account_type IN ('checking', 'savings', 'credit_card', 'investment', 'loan')),
    display_name     TEXT NOT NULL,
    template_json    JSONB NOT NULL,
    page_count       INTEGER NOT NULL DEFAULT 1,
    data_field_count INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pdf_templates_bank_name ON pdf_templates(bank_name);

CREATE TRIGGER trg_pdf_templates_updated_at
    BEFORE UPDATE ON pdf_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Update generation_log to support both V1 schemas and V2 templates
ALTER TABLE generation_log
    ALTER COLUMN schema_id DROP NOT NULL;

ALTER TABLE generation_log
    ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES pdf_templates(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_generation_log_template_id ON generation_log(template_id);
