-- Add admin-defined user_meta form template to source_meta (UI-only, not runtime merge).

ALTER TABLE source_meta
    ADD COLUMN IF NOT EXISTS user_meta_template JSONB NOT NULL DEFAULT '{}'::jsonb;
