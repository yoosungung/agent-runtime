"""Postgres-backed VFS — scoped queries, no full-table loads."""

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

GREP_RESULT_LIMIT = 1000


@dataclass(frozen=True)
class VfsFileRecord:
    path: str
    content: str
    encoding: str = "utf-8"
    modified_at: datetime | None = None


@dataclass(frozen=True)
class VfsEntry:
    path: str
    name: str
    is_dir: bool
    size: int
    modified_at: datetime | None = None


@dataclass(frozen=True)
class VfsGrepMatch:
    path: str
    line: int
    text: str


def _decode_content(raw: bytes, encoding: str) -> str:
    if encoding == "utf-8":
        return raw.decode("utf-8")
    return raw.decode()


def _grep_lines(content: str, pattern: str) -> list[tuple[int, str]]:
    needle = pattern  # literal match (same as prior re.escape behavior)
    out: list[tuple[int, str]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if needle in line:
            out.append((i, line))
    return out


class AgentVfsStore(ABC):
    @abstractmethod
    async def list_dir(self, kind: str, agent_name: str, dir_path: str) -> list[VfsEntry]: ...

    @abstractmethod
    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None: ...

    @abstractmethod
    async def write(
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None: ...

    @abstractmethod
    async def delete(self, kind: str, agent_name: str, path: str) -> None: ...

    @abstractmethod
    async def mkdir(self, kind: str, agent_name: str, dir_path: str) -> None: ...

    @abstractmethod
    async def delete_tree(self, kind: str, agent_name: str, path: str) -> None: ...

    @abstractmethod
    async def glob(
        self,
        kind: str,
        agent_name: str,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]: ...

    @abstractmethod
    async def grep(
        self,
        kind: str,
        agent_name: str,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]: ...


class UserVfsStore(ABC):
    @abstractmethod
    async def list_dir(self, user_id: int, dir_path: str) -> list[VfsEntry]: ...

    @abstractmethod
    async def read(self, user_id: int, path: str) -> VfsFileRecord | None: ...

    @abstractmethod
    async def write(
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None: ...

    @abstractmethod
    async def delete(self, user_id: int, path: str) -> None: ...

    @abstractmethod
    async def mkdir(self, user_id: int, dir_path: str) -> None: ...

    @abstractmethod
    async def delete_tree(self, user_id: int, path: str) -> None: ...

    @abstractmethod
    async def glob(
        self,
        user_id: int,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]: ...

    @abstractmethod
    async def grep(
        self,
        user_id: int,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]: ...


@dataclass
class _MemoryRow:
    path: str
    parent_path: str
    name: str
    is_dir: bool
    size: int
    content: str
    modified_at: datetime


class _MemoryStoreBase:
    def _ensure_dir_rows(self, rows: dict, scope_key: tuple, dir_paths: list[str]) -> None:
        for dir_path in dir_paths:
            path, parent_path, name, size = dir_row_fields(dir_path)
            key = (*scope_key, path)
            if key not in rows:
                rows[key] = _MemoryRow(
                    path=path,
                    parent_path=parent_path,
                    name=name,
                    is_dir=True,
                    size=size,
                    content="",
                    modified_at=datetime.now(UTC),
                )

    def _list_dir_rows(self, rows: list[_MemoryRow], dir_path: str) -> list[VfsEntry]:
        dir_path = normalize_dir(dir_path)
        seen: dict[str, VfsEntry] = {}

        for row in rows:
            if row.parent_path == dir_path:
                seen[row.path] = VfsEntry(
                    path=row.path,
                    name=row.name,
                    is_dir=row.is_dir,
                    size=row.size,
                    modified_at=row.modified_at,
                )

        return sorted(seen.values(), key=lambda e: (not e.is_dir, e.path))

    def _glob_rows(
        self,
        rows: list[_MemoryRow],
        pattern: str,
        *,
        base_path: str | None,
    ) -> list[str]:
        regex = re.compile(glob_to_pg_regex(pattern))
        prefix = path_like_prefix(base_path)
        matched: list[str] = []
        for row in rows:
            if row.is_dir:
                continue
            if prefix is not None and not row.path.startswith(prefix):
                continue
            if regex.match(row.path):
                matched.append(row.path)
        return sorted(matched)

    def _grep_rows(
        self,
        rows: list[_MemoryRow],
        pattern: str,
        *,
        path_prefix: str | None,
        glob_filter: str | None,
    ) -> list[VfsGrepMatch]:
        prefix = path_like_prefix(path_prefix)
        glob_re = re.compile(glob_to_pg_regex(glob_filter)) if glob_filter else None
        matches: list[VfsGrepMatch] = []
        for row in rows:
            if row.is_dir:
                continue
            if prefix is not None and not row.path.startswith(prefix):
                continue
            if glob_re is not None and not glob_re.match(row.path):
                continue
            for line_no, line_text in _grep_lines(row.content, pattern):
                matches.append(VfsGrepMatch(path=row.path, line=line_no, text=line_text))
                if len(matches) >= GREP_RESULT_LIMIT:
                    return matches
        return matches


class MemoryAgentVfsStore(AgentVfsStore, _MemoryStoreBase):
    """In-memory agent VFS for unit tests — same query semantics as Postgres."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], _MemoryRow] = {}

    def _scope_rows(self, kind: str, agent_name: str) -> list[_MemoryRow]:
        return [r for (k, n, _), r in self._rows.items() if k == kind and n == agent_name]

    async def list_dir(self, kind: str, agent_name: str, dir_path: str) -> list[VfsEntry]:
        return self._list_dir_rows(self._scope_rows(kind, agent_name), dir_path)

    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None:
        row = self._rows.get((kind, agent_name, normalize_path(path)))
        if row is None or row.is_dir:
            return None
        return VfsFileRecord(
            path=row.path,
            content=row.content,
            modified_at=row.modified_at,
        )

    async def write(
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        key = (kind, agent_name, norm)
        if not overwrite and key in self._rows:
            raise FileExistsError(f"File already exists: {path}")
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        scope = (kind, agent_name)
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

    async def delete(self, kind: str, agent_name: str, path: str) -> None:
        self._rows.pop((kind, agent_name, normalize_path(path)), None)

    async def mkdir(self, kind: str, agent_name: str, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, size = dir_row_fields(norm)
        scope = (kind, agent_name)
        self._ensure_dir_rows(self._rows, scope, ancestor_dir_paths(parent_path))
        self._rows[(kind, agent_name, path)] = _MemoryRow(
            path=path,
            parent_path=parent_path,
            name=name,
            is_dir=True,
            size=size,
            content="",
            modified_at=datetime.now(UTC),
        )

    async def delete_tree(self, kind: str, agent_name: str, path: str) -> None:
        norm = normalize_path(path)
        row = self._rows.get((kind, agent_name, norm))
        if row is not None and not row.is_dir:
            self._rows.pop((kind, agent_name, norm), None)
            return
        dir_path = normalize_dir(norm)
        keys = [
            key
            for key in list(self._rows)
            if key[0] == kind
            and key[1] == agent_name
            and (key[2] == norm or key[2] == dir_path or key[2].startswith(dir_path))
        ]
        for key in keys:
            self._rows.pop(key, None)

    async def glob(
        self,
        kind: str,
        agent_name: str,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]:
        return self._glob_rows(self._scope_rows(kind, agent_name), pattern, base_path=base_path)

    async def grep(
        self,
        kind: str,
        agent_name: str,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]:
        return self._grep_rows(
            self._scope_rows(kind, agent_name),
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )


class MemoryUserVfsStore(UserVfsStore, _MemoryStoreBase):
    """In-memory user VFS for unit tests."""

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], _MemoryRow] = {}

    def _scope_rows(self, user_id: int) -> list[_MemoryRow]:
        return [r for (uid, _), r in self._rows.items() if uid == user_id]

    async def list_dir(self, user_id: int, dir_path: str) -> list[VfsEntry]:
        return self._list_dir_rows(self._scope_rows(user_id), dir_path)

    async def read(self, user_id: int, path: str) -> VfsFileRecord | None:
        row = self._rows.get((user_id, normalize_path(path)))
        if row is None or row.is_dir:
            return None
        return VfsFileRecord(
            path=row.path,
            content=row.content,
            modified_at=row.modified_at,
        )

    async def write(
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        key = (user_id, norm)
        if not overwrite and key in self._rows:
            raise FileExistsError(f"File already exists: {path}")
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        self._ensure_dir_rows(self._rows, (user_id,), ancestor_dir_paths(parent_path))
        self._rows[key] = _MemoryRow(
            path=norm,
            parent_path=parent_path,
            name=name,
            is_dir=False,
            size=size,
            content=content,
            modified_at=datetime.now(UTC),
        )

    async def delete(self, user_id: int, path: str) -> None:
        self._rows.pop((user_id, normalize_path(path)), None)

    async def mkdir(self, user_id: int, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, size = dir_row_fields(norm)
        self._ensure_dir_rows(self._rows, (user_id,), ancestor_dir_paths(parent_path))
        self._rows[(user_id, path)] = _MemoryRow(
            path=path,
            parent_path=parent_path,
            name=name,
            is_dir=True,
            size=size,
            content="",
            modified_at=datetime.now(UTC),
        )

    async def delete_tree(self, user_id: int, path: str) -> None:
        norm = normalize_path(path)
        row = self._rows.get((user_id, norm))
        if row is not None and not row.is_dir:
            self._rows.pop((user_id, norm), None)
            return
        dir_path = normalize_dir(norm)
        keys = [
            key
            for key in list(self._rows)
            if key[0] == user_id
            and (key[1] == norm or key[1] == dir_path or key[1].startswith(dir_path))
        ]
        for key in keys:
            self._rows.pop(key, None)

    async def glob(
        self,
        user_id: int,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]:
        return self._glob_rows(self._scope_rows(user_id), pattern, base_path=base_path)

    async def grep(
        self,
        user_id: int,
        pattern: str,
        *,
        path_prefix: str | None = None,
        glob_filter: str | None = None,
    ) -> list[VfsGrepMatch]:
        return self._grep_rows(
            self._scope_rows(user_id),
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )


_AGENT_LIST_DIR_SQL = """
SELECT path, name, is_dir, size, modified_at
FROM vfs_agent_files
WHERE kind = $1 AND agent_name = $2 AND parent_path = $3
ORDER BY is_dir DESC, path
"""

_USER_LIST_DIR_SQL = """
SELECT path, name, is_dir, size, modified_at
FROM vfs_user_files
WHERE user_id = $1 AND parent_path = $2
ORDER BY is_dir DESC, path
"""

_AGENT_ENSURE_DIRS_SQL = """
INSERT INTO vfs_agent_files (
    kind, agent_name, path, parent_path, name, is_dir, size, content, encoding
)
VALUES ($1, $2, $3, $4, $5, TRUE, 0, '\\x'::bytea, 'utf-8')
ON CONFLICT (kind, agent_name, path) DO NOTHING
"""

_USER_ENSURE_DIRS_SQL = """
INSERT INTO vfs_user_files (
    user_id, path, parent_path, name, is_dir, size, content, encoding
)
VALUES ($1, $2, $3, $4, TRUE, 0, '\\x'::bytea, 'utf-8')
ON CONFLICT (user_id, path) DO NOTHING
"""


async def _ensure_agent_dirs(conn: Any, kind: str, agent_name: str, parent_path: str) -> None:
    for dir_path in ancestor_dir_paths(parent_path):
        path, p_path, name, _ = dir_row_fields(dir_path)
        await conn.execute(_AGENT_ENSURE_DIRS_SQL, kind, agent_name, path, p_path, name)


async def _ensure_user_dirs(conn: Any, user_id: int, parent_path: str) -> None:
    for dir_path in ancestor_dir_paths(parent_path):
        path, p_path, name, _ = dir_row_fields(dir_path)
        await conn.execute(_USER_ENSURE_DIRS_SQL, user_id, path, p_path, name)


class AsyncpgAgentVfsStore(AgentVfsStore):
    """Postgres agent VFS — indexed parent_path listing, optimized glob, lateral grep."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_dir(self, kind: str, agent_name: str, dir_path: str) -> list[VfsEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _AGENT_LIST_DIR_SQL,
                kind,
                agent_name,
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

    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT path, content, encoding, modified_at
                FROM vfs_agent_files
                WHERE kind = $1 AND agent_name = $2 AND path = $3 AND is_dir = FALSE
                """,
                kind,
                agent_name,
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
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        async with self._pool.acquire() as conn:
            if not overwrite:
                exists = await conn.fetchval(
                    """
                    SELECT 1 FROM vfs_agent_files
                    WHERE kind = $1 AND agent_name = $2 AND path = $3
                    """,
                    kind,
                    agent_name,
                    norm,
                )
                if exists:
                    raise FileExistsError(f"File already exists: {path}")
            await _ensure_agent_dirs(conn, kind, agent_name, parent_path)
            await conn.execute(
                """
                INSERT INTO vfs_agent_files (
                    kind, agent_name, path, parent_path, name, is_dir, size, content, encoding
                )
                VALUES ($1, $2, $3, $4, $5, FALSE, $6, $7, 'utf-8')
                ON CONFLICT (kind, agent_name, path)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    parent_path = EXCLUDED.parent_path,
                    name = EXCLUDED.name,
                    size = EXCLUDED.size,
                    modified_at = now()
                """,
                kind,
                agent_name,
                norm,
                parent_path,
                name,
                size,
                encoded,
            )

    async def delete(self, kind: str, agent_name: str, path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                DELETE FROM vfs_agent_files
                WHERE kind = $1 AND agent_name = $2 AND path = $3
                """,
                kind,
                agent_name,
                normalize_path(path),
            )

    async def mkdir(self, kind: str, agent_name: str, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, _ = dir_row_fields(norm)
        async with self._pool.acquire() as conn:
            await _ensure_agent_dirs(conn, kind, agent_name, parent_path)
            await conn.execute(
                _AGENT_ENSURE_DIRS_SQL,
                kind,
                agent_name,
                path,
                parent_path,
                name,
            )

    async def delete_tree(self, kind: str, agent_name: str, path: str) -> None:
        norm = normalize_path(path)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_dir FROM vfs_agent_files
                WHERE kind = $1 AND agent_name = $2 AND path = $3
                """,
                kind,
                agent_name,
                norm,
            )
            if row is None:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_agent_files
                    WHERE kind = $1 AND agent_name = $2
                      AND (path = $3 OR path LIKE $4)
                    """,
                    kind,
                    agent_name,
                    norm,
                    dir_path + "%",
                )
                return
            if row["is_dir"]:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_agent_files
                    WHERE kind = $1 AND agent_name = $2
                      AND (path = $3 OR path LIKE $4)
                    """,
                    kind,
                    agent_name,
                    dir_path,
                    dir_path + "%",
                )
            else:
                await conn.execute(
                    """
                    DELETE FROM vfs_agent_files
                    WHERE kind = $1 AND agent_name = $2 AND path = $3
                    """,
                    kind,
                    agent_name,
                    norm,
                )

    async def glob(
        self,
        kind: str,
        agent_name: str,
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
                FROM vfs_agent_files
                WHERE kind = $1 AND agent_name = $2
                  AND is_dir = FALSE
                  AND {filter_sql}
                ORDER BY path
                """,
                kind,
                agent_name,
                *filter_params,
            )
        return [row["path"] for row in rows]

    async def grep(
        self,
        kind: str,
        agent_name: str,
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
                FROM vfs_agent_files f
                CROSS JOIN LATERAL (
                    SELECT line_text, ordinality AS line_num
                    FROM unnest(string_to_array(convert_from(f.content, 'UTF8'), E'\\n'))
                        WITH ORDINALITY AS u(line_text, ordinality)
                ) t
                WHERE f.kind = $1 AND f.agent_name = $2
                  AND f.is_dir = FALSE
                  AND ($3::text IS NULL OR f.path LIKE $3 || '%')
                  AND ($4::text IS NULL OR f.path ~ $4)
                  AND t.line_text LIKE '%' || $5 || '%'
                ORDER BY f.path, t.line_num
                LIMIT $6
                """,
                kind,
                agent_name,
                prefix,
                glob_re,
                pattern,
                GREP_RESULT_LIMIT,
            )
        return [
            VfsGrepMatch(path=row["path"], line=row["line_num"], text=row["line_text"])
            for row in rows
        ]


class AsyncpgUserVfsStore(UserVfsStore):
    """Postgres user VFS."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_dir(self, user_id: int, dir_path: str) -> list[VfsEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                _USER_LIST_DIR_SQL,
                user_id,
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

    async def read(self, user_id: int, path: str) -> VfsFileRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT path, content, encoding, modified_at
                FROM vfs_user_files
                WHERE user_id = $1 AND path = $2 AND is_dir = FALSE
                """,
                user_id,
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
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        encoded = content.encode("utf-8")
        parent_path, name, size = vfs_entry_metadata(norm, encoded)
        async with self._pool.acquire() as conn:
            if not overwrite:
                exists = await conn.fetchval(
                    "SELECT 1 FROM vfs_user_files WHERE user_id = $1 AND path = $2",
                    user_id,
                    norm,
                )
                if exists:
                    raise FileExistsError(f"File already exists: {path}")
            await _ensure_user_dirs(conn, user_id, parent_path)
            await conn.execute(
                """
                INSERT INTO vfs_user_files (
                    user_id, path, parent_path, name, is_dir, size, content, encoding
                )
                VALUES ($1, $2, $3, $4, FALSE, $5, $6, 'utf-8')
                ON CONFLICT (user_id, path)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    parent_path = EXCLUDED.parent_path,
                    name = EXCLUDED.name,
                    size = EXCLUDED.size,
                    modified_at = now()
                """,
                user_id,
                norm,
                parent_path,
                name,
                size,
                encoded,
            )

    async def delete(self, user_id: int, path: str) -> None:
        await self.delete_tree(user_id, path)

    async def mkdir(self, user_id: int, dir_path: str) -> None:
        norm = normalize_dir(dir_path)
        if norm == "/":
            return
        path, parent_path, name, _ = dir_row_fields(norm)
        async with self._pool.acquire() as conn:
            await _ensure_user_dirs(conn, user_id, parent_path)
            await conn.execute(
                _USER_ENSURE_DIRS_SQL,
                user_id,
                path,
                parent_path,
                name,
            )

    async def delete_tree(self, user_id: int, path: str) -> None:
        norm = normalize_path(path)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_dir FROM vfs_user_files
                WHERE user_id = $1 AND path = $2
                """,
                user_id,
                norm,
            )
            if row is None:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_user_files
                    WHERE user_id = $1
                      AND (path = $2 OR path LIKE $3)
                    """,
                    user_id,
                    norm,
                    dir_path + "%",
                )
                return
            if row["is_dir"]:
                dir_path = normalize_dir(norm)
                await conn.execute(
                    """
                    DELETE FROM vfs_user_files
                    WHERE user_id = $1
                      AND (path = $2 OR path LIKE $3)
                    """,
                    user_id,
                    dir_path,
                    dir_path + "%",
                )
            else:
                await conn.execute(
                    """
                    DELETE FROM vfs_user_files
                    WHERE user_id = $1 AND path = $2
                    """,
                    user_id,
                    norm,
                )

    async def glob(
        self,
        user_id: int,
        pattern: str,
        *,
        base_path: str | None = None,
    ) -> list[str]:
        filter_sql, filter_params, _ = glob_path_filter_sql(
            pattern, base_path, start_param=2
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT path
                FROM vfs_user_files
                WHERE user_id = $1
                  AND is_dir = FALSE
                  AND {filter_sql}
                ORDER BY path
                """,
                user_id,
                *filter_params,
            )
        return [row["path"] for row in rows]

    async def grep(
        self,
        user_id: int,
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
                FROM vfs_user_files f
                CROSS JOIN LATERAL (
                    SELECT line_text, ordinality AS line_num
                    FROM unnest(string_to_array(convert_from(f.content, 'UTF8'), E'\\n'))
                        WITH ORDINALITY AS u(line_text, ordinality)
                ) t
                WHERE f.user_id = $1
                  AND f.is_dir = FALSE
                  AND ($2::text IS NULL OR f.path LIKE $2 || '%')
                  AND ($3::text IS NULL OR f.path ~ $3)
                  AND t.line_text LIKE '%' || $4 || '%'
                ORDER BY f.path, t.line_num
                LIMIT $5
                """,
                user_id,
                prefix,
                glob_re,
                pattern,
                GREP_RESULT_LIMIT,
            )
        return [
            VfsGrepMatch(path=row["path"], line=row["line_num"], text=row["line_text"])
            for row in rows
        ]


def asyncpg_pool_kwargs(dsn: str, *, pgbouncer: bool = False) -> tuple[str, dict[str, Any]]:
    """Return (clean_dsn, connect kwargs) for asyncpg.create_pool."""
    from runtime_common.db.engine import _strip_sslmode

    clean_dsn, sslmode = _strip_sslmode(dsn)
    kwargs: dict[str, Any] = {}
    if sslmode == "disable":
        kwargs["ssl"] = False
    if pgbouncer:
        kwargs["statement_cache_size"] = 0
    return clean_dsn, kwargs


async def create_asyncpg_pool(
    dsn: str,
    *,
    pgbouncer: bool = False,
    min_size: int = 2,
    max_size: int = 10,
) -> Any:
    import asyncpg

    clean_dsn, connect_kwargs = asyncpg_pool_kwargs(dsn, pgbouncer=pgbouncer)
    return await asyncpg.create_pool(
        clean_dsn,
        min_size=min_size,
        max_size=max_size,
        **connect_kwargs,
    )
