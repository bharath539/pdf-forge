-- PDF Forge: Initial Schema
-- Only stores format schemas and generation logs. NEVER stores user data or PII.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE format_schemas (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_name     TEXT NOT NULL,
    account_type  TEXT NOT NULL CHECK (account_type IN ('checking', 'savings', 'credit_card', 'investment', 'loan')),
    display_name  TEXT NOT NULL,
    schema_json   JSONB NOT NULL,
    page_count    INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(bank_name, account_type)
);

CREATE TABLE generation_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_id     UUID NOT NULL REFERENCES format_schemas(id) ON DELETE CASCADE,
    scenario      TEXT NOT NULL,
    parameters    JSONB NOT NULL,
    file_count    INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_generation_log_schema_id ON generation_log(schema_id);
CREATE INDEX idx_generation_log_created_at ON generation_log(created_at DESC);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_format_schemas_updated_at
    BEFORE UPDATE ON format_schemas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
