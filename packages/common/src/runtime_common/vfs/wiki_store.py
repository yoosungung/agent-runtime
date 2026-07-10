"""Postgres-backed wiki VFS — scoped by (tenant, project_id)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from runtime_common.vfs.dirs import ancestor_dir_paths, dir_row_fields
from runtime_common.vfs.glob_query import glob_path_filter_sql
from runtime_common.vfs.paths import (
    glob_to_pg_regex,
    normalize_dir,
    normalize_path,
    path_like_prefix,
    vfs_entry_metadata,
)
from runtime_common.vfs.store import (
    GREP_RESULT_LIMIT,
    VfsEntry,
    VfsFileRecord,
    VfsGrepMatch,
    _MemoryRow,
    _MemoryStoreBase,
    _decode_content,
    _grep_lines,
)


class WikiVfsStore(ABC):
    @abstractmethod
    async def list_dir(self, tenant: str, project_id: str, dir_path: str) -> list[VfsEntry]: ...

    @abstractmethod
    async def read(self, tenant: str, project_id: str, path: str) -> VfsFileRecord | None: ...

    @abstractmethod
    async def write(
        self, tenant: str, project_id: str, path: str, content: str, *, overwrite: bool = False
    ) -> None: ...

    @abstractmethod
    async def delete(self, tenant: str, project_id: str, path: str) -> None: ...

    @abstractmethod
    async def mkdir(self, tenant: str, project_id: str, dir_path: str) -> None: ...

    @abstractmethod
    async def delete_tree(self, tenant: str, project_id: str, path: str) -> None: ...

    @abstractmethod
    async def glob(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]: ...

    @abstractmethod
    async def grep(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]: ...


@dataclass
class WikiVfsStats:
    file_count: int = 0
    total_bytes: int = 0
    last_modified: datetime | None = None


class MemoryWikiVfsStore(WikiVfsStore, _MemoryStoreBase):
    """In-memory wiki VFS for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], _MemoryRow] = {}

    def _scope_key(self, tenant: str, project_id: str) -> tuple[str, str]:
        return (tenant, project_id)

    def _scope_rows(self, tenant: str, project_id: str) -> list[_MemoryRow]:
        return [r for (t, p, _), r in self._rows.items() if t == tenant and p == project_id]

    async def list_dir(self, tenant: str, project_id: str, dir_path: str) -> list[VfsEntry]:
        return self._list_dir_rows(self._scope_rows(tenant, project_id), dir_path)

    async def read(self, tenant: str, project_id: str, path: str) -> VfsFileRecord | None:
        row = self._rows.get((tenant, project_id, normalize_path(path)))
        if row is None or row.is_dir:
            return None
        return VfsFileRecord(path=row.path, content=row.content, modified_at=row.modified_at)

    async def write(
        self, tenant: str, project_id: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        key = (tenant, project_id, norm)
        if not overwrite and key in self._rows:
            raise FileExistsError(f"File already exists: {path}")
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        scope = self._scope_key(tenant, project_id)
        self._ensure_dir_rows(self._rows, scope, ancestor_dir_paths(parent_path))
        self._rows[key] = _MemoryRow(
            path=norm,
            parent_path=parent_path,
            name=name,
            is_dir=False,
            size=size,
            content=content,
            modified_at=datetime.now(UTC),
        )

    async def delete(self, tenant: str, project_id: str, path: str) -> None:
        self._rows.pop((tenant, project_id, normalize_path(path)), None)

    async def mkdir(self, tenant: str, project_id: str, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, size = dir_row_fields(norm)
        scope = self._scope_key(tenant, project_id)
        self._ensure_dir_rows(self._rows, scope, ancestor_dir_paths(parent_path))
        self._rows[(tenant, project_id, path)] = _MemoryRow(
            path=path,
            parent_path=parent_path,
            name=name,
            is_dir=True,
            size=size,
            content="",
            modified_at=datetime.now(UTC),
        )

    async def delete_tree(self, tenant: str, project_id: str, path: str) -> None:
        norm = normalize_path(path)
        dir_path = normalize_dir(norm)
        keys = [
            key
            for key in list(self._rows)
            if key[0] == tenant
            and key[1] == project_id
            and (key[2] == norm or key[2] == dir_path or key[2].startswith(dir_path))
        ]
        for key in keys:
            self._rows.pop(key, None)

    async def glob(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]:
        return self._glob_rows(
            self._scope_rows(tenant, project_id), pattern, base_path=base_path
        )

    async def grep(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]:
        return self._grep_rows(
            self._scope_rows(tenant, project_id),
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )


_WIKI_LIST_DIR_SQL = """
SELECT path, name, is_dir, size, modified_at
FROM vfs_wiki_files
WHERE tenant = $1 AND project_id = $2::uuid AND parent_path = $3
ORDER BY is_dir DESC, path
"""

_WIKI_ENSURE_DIRS_SQL = """
INSERT INTO vfs_wiki_files (
    tenant, project_id, path, parent_path, name, is_dir, size, content, encoding
)
VALUES ($1, $2::uuid, $3, $4, $5, TRUE, 0, '\\x'::bytea, 'utf-8')
ON CONFLICT (tenant, project_id, path) DO NOTHING
"""


async def _ensure_wiki_dirs(conn: Any, tenant: str, project_id: str, parent_path: str) -> None:
    for dir_path in ancestor_dir_paths(parent_path):
        path, p_path, name, _ = dir_row_fields(dir_path)
        await conn.execute(_WIKI_ENSURE_DIRS_SQL, tenant, project_id, path, p_path, name)


class AsyncpgWikiVfsStore(WikiVfsStore):
    """Postgres wiki VFS."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_dir(self, tenant: str, project_id: str, dir_path: str) -> list[VfsEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _WIKI_LIST_DIR_SQL,
                tenant,
                project_id,
                normalize_dir(dir_path),
            )
        return [
            VfsEntry(
                path=row["path"],
                name=row["name"],
                is_dir=row["is_dir"],
                size=row["size"],
                modified_at=row["modified_at"],
            )
            for row in rows
        ]

    async def read(self, tenant: str, project_id: str, path: str) -> VfsFileRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT path, content, encoding, modified_at
                FROM vfs_wiki_files
                WHERE tenant = $1 AND project_id = $2::uuid AND path = $3 AND is_dir = FALSE
                """,
                tenant,
                project_id,
                normalize_path(path),
            )
        if row is None:
            return None
        return VfsFileRecord(
            path=row["path"],
            content=_decode_content(row["content"], row["encoding"]),
            encoding=row["encoding"],
            modified_at=row["modified_at"],
        )

    async def write(
        self, tenant: str, project_id: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        async with self._pool.acquire() as conn:
            if not overwrite:
                exists = await conn.fetchval(
                    """
                    SELECT 1 FROM vfs_wiki_files
                    WHERE tenant = $1 AND project_id = $2::uuid AND path = $3
                    """,
                    tenant,
                    project_id,
                    norm,
                )
                if exists:
                    raise FileExistsError(f"File already exists: {path}")
            await _ensure_wiki_dirs(conn, tenant, project_id, parent_path)
            await conn.execute(
                """
                INSERT INTO vfs_wiki_files (
                    tenant, project_id, path, parent_path, name, is_dir, size, content, encoding
                )
                VALUES ($1, $2::uuid, $3, $4, $5, FALSE, $6, $7, 'utf-8')
                ON CONFLICT (tenant, project_id, path)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    parent_path = EXCLUDED.parent_path,
                    name = EXCLUDED.name,
                    size = EXCLUDED.size,
                    modified_at = now()
                """,
                tenant,
                project_id,
                norm,
                parent_path,
                name,
                size,
                encoded,
            )

    async def delete(self, tenant: str, project_id: str, path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM vfs_wiki_files
                WHERE tenant = $1 AND project_id = $2::uuid AND path = $3
                """,
                tenant,
                project_id,
                normalize_path(path),
            )

    async def mkdir(self, tenant: str, project_id: str, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, _ = dir_row_fields(norm)
        async with self._pool.acquire() as conn:
            await _ensure_wiki_dirs(conn, tenant, project_id, parent_path)
            await conn.execute(
                _WIKI_ENSURE_DIRS_SQL,
                tenant,
                project_id,
                path,
                parent_path,
                name,
            )

    async def delete_tree(self, tenant: str, project_id: str, path: str) -> None:
        norm = normalize_path(path)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_dir FROM vfs_wiki_files
                WHERE tenant = $1 AND project_id = $2::uuid AND path = $3
                """,
                tenant,
                project_id,
                norm,
            )
            if row is None:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_wiki_files
                    WHERE tenant = $1 AND project_id = $2::uuid
                      AND (path = $3 OR path LIKE $4)
                    """,
                    tenant,
                    project_id,
                    norm,
                    dir_path + "%",
                )
                return
            if row["is_dir"]:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_wiki_files
                    WHERE tenant = $1 AND project_id = $2::uuid
                      AND (path = $3 OR path LIKE $4)
                    """,
                    tenant,
                    project_id,
                    dir_path,
                    dir_path + "%",
                )
            else:
                await conn.execute(
                    """
                    DELETE FROM vfs_wiki_files
                    WHERE tenant = $1 AND project_id = $2::uuid AND path = $3
                    """,
                    tenant,
                    project_id,
                    norm,
                )

    async def glob(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]:
        filter_sql, filter_params, _ = glob_path_filter_sql(
            pattern, base_path, start_param=3
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT path
                FROM vfs_wiki_files
                WHERE tenant = $1 AND project_id = $2::uuid
                  AND is_dir = FALSE
                  AND {filter_sql}
                ORDER BY path
                """,
                tenant,
                project_id,
                *filter_params,
            )
        return [row["path"] for row in rows]

    async def grep(
        self,
        tenant: str,
        project_id: str,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]:
        prefix = path_like_prefix(path_prefix)
        glob_re = glob_to_pg_regex(glob_filter) if glob_filter else None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT f.path, t.line_num::int AS line_num, t.line_text
                FROM vfs_wiki_files f
                CROSS JOIN LATERAL (
                    SELECT line_text, ordinality AS line_num
                    FROM unnest(string_to_array(convert_from(f.content, 'UTF8'), E'\\n'))
                        WITH ORDINALITY AS u(line_text, ordinality)
                ) t
                WHERE f.tenant = $1 AND f.project_id = $2::uuid
                  AND f.is_dir = FALSE
                  AND ($3::text IS NULL OR f.path LIKE $3 || '%')
                  AND ($4::text IS NULL OR f.path ~ $4)
                  AND t.line_text LIKE '%' || $5 || '%'
                ORDER BY f.path, t.line_num
                LIMIT $6
                """,
                tenant,
                project_id,
                prefix,
                glob_re,
                pattern,
                GREP_RESULT_LIMIT,
            )
        return [
            VfsGrepMatch(path=row["path"], line=row["line_num"], text=row["line_text"])
            for row in rows
        ]

    async def project_stats(self, tenant: str, project_id: str) -> WikiVfsStats:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE NOT is_dir)::int AS file_count,
                    COALESCE(SUM(size) FILTER (WHERE NOT is_dir), 0)::int AS total_bytes,
                    MAX(modified_at) FILTER (WHERE NOT is_dir) AS last_modified
                FROM vfs_wiki_files
                WHERE tenant = $1 AND project_id = $2::uuid
                """,
                tenant,
                project_id,
            )
        if row is None:
            return WikiVfsStats()
        return WikiVfsStats(
            file_count=row["file_count"] or 0,
            total_bytes=row["total_bytes"] or 0,
            last_modified=row["last_modified"],
        )
