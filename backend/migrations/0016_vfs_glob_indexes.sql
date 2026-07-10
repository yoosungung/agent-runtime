-- VFS glob query indexes — pg_trgm on name, varchar_pattern_ops on path.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_vfs_agent_files_path_prefix
    ON vfs_agent_files (kind, agent_name, path varchar_pattern_ops);

CREATE INDEX IF NOT EXISTS ix_vfs_agent_files_name_trgm
    ON vfs_agent_files USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_vfs_user_files_path_prefix
    ON vfs_user_files (user_id, path varchar_pattern_ops);

CREATE INDEX IF NOT EXISTS ix_vfs_user_files_name_trgm
    ON vfs_user_files USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_vfs_wiki_files_path_prefix
    ON vfs_wiki_files (tenant, project_id, path varchar_pattern_ops);

CREATE INDEX IF NOT EXISTS ix_vfs_wiki_files_name_trgm
    ON vfs_wiki_files USING gin (name gin_trgm_ops);
