-- Upgrade existing vfs_* tables: parent_path, name, is_dir, size + list indexes.
-- Fresh installs from 0001_init.sql already include these columns (no-op via IF NOT EXISTS).

ALTER TABLE vfs_agent_files
    ADD COLUMN IF NOT EXISTS parent_path TEXT,
    ADD COLUMN IF NOT EXISTS name TEXT,
    ADD COLUMN IF NOT EXISTS is_dir BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS size INTEGER NOT NULL DEFAULT 0;

UPDATE vfs_agent_files
SET
    parent_path = CASE
        WHEN path ~ '^/[^/]+$' THEN '/'
        ELSE regexp_replace(path, '/[^/]+$', '/')
    END,
    name = CASE
        WHEN path ~ '^/[^/]+$' THEN ltrim(path, '/')
        ELSE regexp_replace(path, '^.*/', '')
    END,
    size = octet_length(content)
WHERE parent_path IS NULL OR name IS NULL;

ALTER TABLE vfs_agent_files
    ALTER COLUMN parent_path SET NOT NULL,
    ALTER COLUMN name SET NOT NULL;

ALTER TABLE vfs_user_files
    ADD COLUMN IF NOT EXISTS parent_path TEXT,
    ADD COLUMN IF NOT EXISTS name TEXT,
    ADD COLUMN IF NOT EXISTS is_dir BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS size INTEGER NOT NULL DEFAULT 0;

UPDATE vfs_user_files
SET
    parent_path = CASE
        WHEN path ~ '^/[^/]+$' THEN '/'
        ELSE regexp_replace(path, '/[^/]+$', '/')
    END,
    name = CASE
        WHEN path ~ '^/[^/]+$' THEN ltrim(path, '/')
        ELSE regexp_replace(path, '^.*/', '')
    END,
    size = octet_length(content)
WHERE parent_path IS NULL OR name IS NULL;

ALTER TABLE vfs_user_files
    ALTER COLUMN parent_path SET NOT NULL,
    ALTER COLUMN name SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_vfs_agent_files_parent ON vfs_agent_files (kind, agent_name, parent_path);
CREATE INDEX IF NOT EXISTS ix_vfs_user_files_parent ON vfs_user_files (user_id, parent_path);
