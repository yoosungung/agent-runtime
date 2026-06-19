"""VFS persistence layer — agent and user scoped file storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime_common.vfs.paths import normalize_path


@dataclass(frozen=True)
class VfsFileRecord:
    path: str
    content: str
    encoding: str = "utf-8"
    modified_at: datetime | None = None


class AgentVfsStore(ABC):
    @abstractmethod
    async def list_paths(self, kind: str, agent_name: str) -> list[str]: ...

    @abstractmethod
    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None: ...

    @abstractmethod
    async def write(
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None: ...

    @abstractmethod
    async def delete(self, kind: str, agent_name: str, path: str) -> None: ...


class UserVfsStore(ABC):
    @abstractmethod
    async def list_paths(self, user_id: int) -> list[str]: ...

    @abstractmethod
    async def read(self, user_id: int, path: str) -> VfsFileRecord | None: ...

    @abstractmethod
    async def write(
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None: ...

    @abstractmethod
    async def delete(self, user_id: int, path: str) -> None: ...


class MemoryAgentVfsStore(AgentVfsStore):
    """In-memory agent VFS for unit tests."""

    def __init__(self) -> None:
        self._files: dict[tuple[str, str, str], VfsFileRecord] = {}

    async def list_paths(self, kind: str, agent_name: str) -> list[str]:
        prefix = (kind, agent_name)
        return sorted(
            path for (k, n, path) in self._files if (k, n) == prefix
        )

    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None:
        return self._files.get((kind, agent_name, normalize_path(path)))

    async def write(
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        key = (kind, agent_name, normalize_path(path))
        if not overwrite and key in self._files:
            raise FileExistsError(f"File already exists: {path}")
        self._files[key] = VfsFileRecord(
            path=normalize_path(path),
            content=content,
            modified_at=datetime.now(timezone.utc),
        )

    async def delete(self, kind: str, agent_name: str, path: str) -> None:
        self._files.pop((kind, agent_name, normalize_path(path)), None)


class MemoryUserVfsStore(UserVfsStore):
    """In-memory user VFS for unit tests."""

    def __init__(self) -> None:
        self._files: dict[tuple[int, str], VfsFileRecord] = {}

    async def list_paths(self, user_id: int) -> list[str]:
        return sorted(path for (uid, path) in self._files if uid == user_id)

    async def read(self, user_id: int, path: str) -> VfsFileRecord | None:
        return self._files.get((user_id, normalize_path(path)))

    async def write(
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        key = (user_id, normalize_path(path))
        if not overwrite and key in self._files:
            raise FileExistsError(f"File already exists: {path}")
        self._files[key] = VfsFileRecord(
            path=normalize_path(path),
            content=content,
            modified_at=datetime.now(timezone.utc),
        )

    async def delete(self, user_id: int, path: str) -> None:
        self._files.pop((user_id, normalize_path(path)), None)


class AsyncpgAgentVfsStore(AgentVfsStore):
    """Postgres-backed agent VFS using asyncpg."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_paths(self, kind: str, agent_name: str) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT path FROM vfs_agent_files WHERE kind = $1 AND agent_name = $2 ORDER BY path",
                kind,
                agent_name,
            )
        return [row["path"] for row in rows]

    async def read(self, kind: str, agent_name: str, path: str) -> VfsFileRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT path, content, encoding, modified_at
                FROM vfs_agent_files
                WHERE kind = $1 AND agent_name = $2 AND path = $3
                """,
                kind,
                agent_name,
                normalize_path(path),
            )
        if row is None:
            return None
        content = row["content"].decode("utf-8") if row["encoding"] == "utf-8" else row["content"].decode()
        return VfsFileRecord(
            path=row["path"],
            content=content,
            encoding=row["encoding"],
            modified_at=row["modified_at"],
        )

    async def write(
        self, kind: str, agent_name: str, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        async with self._pool.acquire() as conn:
            if not overwrite:
                exists = await conn.fetchval(
                    "SELECT 1 FROM vfs_agent_files WHERE kind=$1 AND agent_name=$2 AND path=$3",
                    kind,
                    agent_name,
                    norm,
                )
                if exists:
                    raise FileExistsError(f"File already exists: {path}")
            await conn.execute(
                """
                INSERT INTO vfs_agent_files (kind, agent_name, path, content, encoding)
                VALUES ($1, $2, $3, $4, 'utf-8')
                ON CONFLICT (kind, agent_name, path)
                DO UPDATE SET content = EXCLUDED.content, modified_at = now()
                """,
                kind,
                agent_name,
                norm,
                content.encode("utf-8"),
            )

    async def delete(self, kind: str, agent_name: str, path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM vfs_agent_files WHERE kind=$1 AND agent_name=$2 AND path=$3",
                kind,
                agent_name,
                normalize_path(path),
            )


class AsyncpgUserVfsStore(UserVfsStore):
    """Postgres-backed user VFS using asyncpg."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def list_paths(self, user_id: int) -> list[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT path FROM vfs_user_files WHERE user_id = $1 ORDER BY path",
                user_id,
            )
        return [row["path"] for row in rows]

    async def read(self, user_id: int, path: str) -> VfsFileRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT path, content, encoding, modified_at
                FROM vfs_user_files WHERE user_id = $1 AND path = $2
                """,
                user_id,
                normalize_path(path),
            )
        if row is None:
            return None
        content = row["content"].decode("utf-8") if row["encoding"] == "utf-8" else row["content"].decode()
        return VfsFileRecord(
            path=row["path"],
            content=content,
            encoding=row["encoding"],
            modified_at=row["modified_at"],
        )

    async def write(
        self, user_id: int, path: str, content: str, *, overwrite: bool = False
    ) -> None:
        norm = normalize_path(path)
        async with self._pool.acquire() as conn:
            if not overwrite:
                exists = await conn.fetchval(
                    "SELECT 1 FROM vfs_user_files WHERE user_id=$1 AND path=$2",
                    user_id,
                    norm,
                )
                if exists:
                    raise FileExistsError(f"File already exists: {path}")
            await conn.execute(
                """
                INSERT INTO vfs_user_files (user_id, path, content, encoding)
                VALUES ($1, $2, $3, 'utf-8')
                ON CONFLICT (user_id, path)
                DO UPDATE SET content = EXCLUDED.content, modified_at = now()
                """,
                user_id,
                norm,
                content.encode("utf-8"),
            )

    async def delete(self, user_id: int, path: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM vfs_user_files WHERE user_id = $1 AND path = $2",
                user_id,
                normalize_path(path),
            )


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


async def create_asyncpg_pool(dsn: str, *, pgbouncer: bool = False) -> Any:
    import asyncpg

    clean_dsn, connect_kwargs = asyncpg_pool_kwargs(dsn, pgbouncer=pgbouncer)
    return await asyncpg.create_pool(clean_dsn, **connect_kwargs)
