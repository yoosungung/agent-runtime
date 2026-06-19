-- Migration 0003: general agent tier + VFS tables
--
-- Extends source_meta deploy_mode with 'general'.
-- Adds vfs_agent_files (shared per logical agent) and vfs_user_files (per user).

-- ---------------------------------------------------------------------------
-- source_meta: general deploy mode
-- ---------------------------------------------------------------------------

ALTER TABLE source_meta DROP CONSTRAINT IF EXISTS chk_source_meta_deploy_mode;
ALTER TABLE source_meta ADD CONSTRAINT chk_source_meta_deploy_mode
    CHECK (deploy_mode IN ('bundle', 'image', 'general'));

ALTER TABLE source_meta DROP CONSTRAINT IF EXISTS chk_source_meta_general_fields;
ALTER TABLE source_meta ADD CONSTRAINT chk_source_meta_general_fields
    CHECK (
        deploy_mode != 'general'
        OR (
            entrypoint IS NULL AND bundle_uri IS NULL AND checksum IS NULL
            AND image_uri IS NULL AND slug IS NULL
            AND kind = 'agent' AND runtime_pool = 'agent:compiled_graph'
        )
    );

-- ---------------------------------------------------------------------------
-- VFS tables
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vfs_agent_files (
    kind        VARCHAR(16)  NOT NULL DEFAULT 'agent',
    agent_name  VARCHAR(128) NOT NULL,
    path        TEXT         NOT NULL,
    content     BYTEA        NOT NULL,
    encoding    VARCHAR(8)   NOT NULL DEFAULT 'utf-8',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    modified_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, agent_name, path)
);

CREATE TABLE IF NOT EXISTS vfs_user_files (
    user_id     BIGINT       NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path        TEXT         NOT NULL,
    content     BYTEA        NOT NULL,
    encoding    VARCHAR(8)   NOT NULL DEFAULT 'utf-8',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    modified_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, path)
);
