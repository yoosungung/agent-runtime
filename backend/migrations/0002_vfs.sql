-- agents-runtime — VFS tables (general agent tier)
-- Requires: users (0001_init.sql)
-- path-graph vfs_triggers.sql applies after this on the same DSN (VFS_DSN).

CREATE TABLE IF NOT EXISTS vfs_agent_files (
    kind        VARCHAR(16)  NOT NULL DEFAULT 'agent',
    agent_name  VARCHAR(128) NOT NULL,
    path        TEXT         NOT NULL,
    parent_path TEXT         NOT NULL,
    name        TEXT         NOT NULL,
    is_dir      BOOLEAN      NOT NULL DEFAULT FALSE,
    size        INTEGER      NOT NULL DEFAULT 0,
    content     BYTEA        NOT NULL,
    encoding    VARCHAR(8)   NOT NULL DEFAULT 'utf-8',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    modified_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, agent_name, path)
);

CREATE TABLE IF NOT EXISTS vfs_user_files (
    user_id     BIGINT       NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    path        TEXT         NOT NULL,
    parent_path TEXT         NOT NULL,
    name        TEXT         NOT NULL,
    is_dir      BOOLEAN      NOT NULL DEFAULT FALSE,
    size        INTEGER      NOT NULL DEFAULT 0,
    content     BYTEA        NOT NULL,
    encoding    VARCHAR(8)   NOT NULL DEFAULT 'utf-8',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    modified_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, path)
);

CREATE INDEX IF NOT EXISTS ix_vfs_agent_files_parent
    ON vfs_agent_files (kind, agent_name, parent_path);

CREATE INDEX IF NOT EXISTS ix_vfs_user_files_parent
    ON vfs_user_files (user_id, parent_path);
