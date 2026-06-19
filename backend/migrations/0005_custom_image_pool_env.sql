-- Persist K8s pool env for custom image deployments (admin UI edit round-trip).
ALTER TABLE source_meta
    ADD COLUMN IF NOT EXISTS pool_env JSONB NOT NULL DEFAULT '{}';
