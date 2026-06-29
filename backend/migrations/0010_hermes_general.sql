-- Hermes profile general tier (deploy_mode=hermes_general, runtime_pool=agent:hermes)

ALTER TABLE source_meta DROP CONSTRAINT IF EXISTS chk_source_meta_deploy_mode;
ALTER TABLE source_meta ADD CONSTRAINT chk_source_meta_deploy_mode
    CHECK (deploy_mode IN ('bundle', 'image', 'general', 'hermes_general'));

ALTER TABLE source_meta ADD CONSTRAINT chk_source_meta_hermes_general_fields
    CHECK (
        deploy_mode != 'hermes_general'
        OR (
            entrypoint IS NULL AND bundle_uri IS NULL AND checksum IS NULL
            AND image_uri IS NULL AND slug IS NULL
            AND kind = 'agent' AND runtime_pool = 'agent:hermes'
        )
    );

CREATE INDEX IF NOT EXISTS ix_source_meta_hermes_visibility
    ON source_meta (deploy_mode, visibility)
    WHERE deploy_mode = 'hermes_general' AND retired = FALSE;
