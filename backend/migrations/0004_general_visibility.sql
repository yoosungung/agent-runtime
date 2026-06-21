-- General agent ownership + visibility (private | tenant | public)

ALTER TABLE source_meta
    ADD COLUMN IF NOT EXISTS created_by_user_id BIGINT REFERENCES users (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owner_tenant VARCHAR(64),
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private';

ALTER TABLE source_meta DROP CONSTRAINT IF EXISTS chk_source_meta_visibility;
ALTER TABLE source_meta
    ADD CONSTRAINT chk_source_meta_visibility
    CHECK (visibility IN ('private', 'tenant', 'public'));

CREATE INDEX IF NOT EXISTS ix_source_meta_general_visibility
    ON source_meta (deploy_mode, visibility)
    WHERE deploy_mode = 'general' AND retired = FALSE;
