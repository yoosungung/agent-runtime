-- Wiki VFS — pipeline GraphRAG wiki pages (tenant + project_id scope).
-- Requires: path_graph.projects (path-graph migrate on same DSN).

CREATE TABLE IF NOT EXISTS vfs_wiki_files (
    tenant       TEXT NOT NULL,
    project_id   UUID NOT NULL,
    path         TEXT NOT NULL,
    parent_path  TEXT NOT NULL,
    name         TEXT NOT NULL,
    is_dir       BOOLEAN NOT NULL DEFAULT FALSE,
    size         INTEGER NOT NULL DEFAULT 0,
    content      BYTEA NOT NULL,
    encoding     VARCHAR(8) NOT NULL DEFAULT 'utf-8',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    modified_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, project_id, path)
);

CREATE INDEX IF NOT EXISTS ix_vfs_wiki_files_parent
    ON vfs_wiki_files (tenant, project_id, parent_path);
