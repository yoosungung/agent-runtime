"""Database-backed deepagents VFS backends — async API only."""

from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileData,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import perform_string_replacement

from runtime_common.vfs.paths import format_read_content, normalize_dir, normalize_path, utc_now_iso
from runtime_common.vfs.store import AgentVfsStore, UserVfsStore, VfsEntry


def _entry_to_dict(entry: VfsEntry) -> dict:
    out: dict = {"path": entry.path, "is_dir": entry.is_dir}
    if not entry.is_dir:
        out["modified_at"] = entry.modified_at.isoformat() if entry.modified_at else utc_now_iso()
    return out


class _DatabaseBackendBase(BackendProtocol):
    """DeepAgents backend — each operation maps to one scoped store query."""

    async def _list_dir(self, dir_path: str) -> list[VfsEntry]:
        raise NotImplementedError

    async def _read_content(self, path: str) -> str | None:
        raise NotImplementedError

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        raise NotImplementedError

    async def _glob_paths(self, pattern: str, base_path: str | None) -> list[str]:
        raise NotImplementedError

    async def _grep_matches(
        self,
        pattern: str,
        *,
        path_prefix: str | None,
        glob_filter: str | None,
    ) -> list[dict]:
        raise NotImplementedError

    async def als(self, path: str) -> LsResult:
        entries = await self._list_dir(normalize_dir(path))
        return LsResult(entries=[_entry_to_dict(e) for e in entries])

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        file_path = normalize_path(file_path)
        content = await self._read_content(file_path)
        if content is None:
            return ReadResult(error=f"Error: File '{file_path}' not found")
        formatted = format_read_content(content, offset=offset, limit=limit)
        return ReadResult(file_data=FileData(content=formatted, encoding="utf-8"))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        file_path = normalize_path(file_path)
        try:
            await self._write_content(file_path, content, overwrite=False)
        except FileExistsError:
            return WriteResult(
                error=(
                    f"Cannot write to {file_path} because it already exists. "
                    "Read and then make an edit, or write to a new path."
                )
            )
        except OSError as exc:
            return WriteResult(error=f"Error writing file '{file_path}': {exc}")
        return WriteResult(path=file_path)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        file_path = normalize_path(file_path)
        content = await self._read_content(file_path)
        if content is None:
            return EditResult(error=f"Error: File '{file_path}' not found")
        new_content, count = perform_string_replacement(
            content, old_string, new_string, replace_all=replace_all
        )
        if count == 0:
            return EditResult(error=f"Error: String not found in '{file_path}'")
        try:
            await self._write_content(file_path, new_content, overwrite=True)
        except OSError as exc:
            return EditResult(error=f"Error editing file '{file_path}': {exc}")
        return EditResult(path=file_path, occurrences=count)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        matched = await self._glob_paths(pattern, path)
        return GlobResult(matches=matched)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        matches = await self._grep_matches(
            pattern,
            path_prefix=path,
            glob_filter=glob,
        )
        return GrepResult(matches=matches)


class AgentDatabaseBackend(_DatabaseBackendBase):
    """Persistent VFS scoped by ``(kind, agent_name)`` — shared across users and versions."""

    def __init__(self, store: AgentVfsStore, kind: str, agent_name: str) -> None:
        self._store = store
        self._kind = kind
        self._agent_name = agent_name

    async def _list_dir(self, dir_path: str) -> list[VfsEntry]:
        return await self._store.list_dir(self._kind, self._agent_name, dir_path)

    async def _read_content(self, path: str) -> str | None:
        record = await self._store.read(self._kind, self._agent_name, path)
        return None if record is None else record.content

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        await self._store.write(self._kind, self._agent_name, path, content, overwrite=overwrite)

    async def _glob_paths(self, pattern: str, base_path: str | None) -> list[str]:
        return await self._store.glob(self._kind, self._agent_name, pattern, base_path=base_path)

    async def _grep_matches(
        self,
        pattern: str,
        *,
        path_prefix: str | None,
        glob_filter: str | None,
    ) -> list[dict]:
        rows = await self._store.grep(
            self._kind,
            self._agent_name,
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )
        return [{"path": r.path, "line": r.line, "text": r.text} for r in rows]


class UserDatabaseBackend(_DatabaseBackendBase):
    """Persistent VFS scoped by ``user_id`` — personal cross-agent area."""

    def __init__(self, store: UserVfsStore, user_id: int) -> None:
        self._store = store
        self._user_id = user_id

    async def _list_dir(self, dir_path: str) -> list[VfsEntry]:
        return await self._store.list_dir(self._user_id, dir_path)

    async def _read_content(self, path: str) -> str | None:
        record = await self._store.read(self._user_id, path)
        return None if record is None else record.content

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        await self._store.write(self._user_id, path, content, overwrite=overwrite)

    async def _glob_paths(self, pattern: str, base_path: str | None) -> list[str]:
        return await self._store.glob(self._user_id, pattern, base_path=base_path)

    async def _grep_matches(
        self,
        pattern: str,
        *,
        path_prefix: str | None,
        glob_filter: str | None,
    ) -> list[dict]:
        rows = await self._store.grep(
            self._user_id,
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )
        return [{"path": r.path, "line": r.line, "text": r.text} for r in rows]


class WikiDatabaseBackend(_DatabaseBackendBase):
    """Persistent VFS scoped by ``(tenant, project_id)`` — pipeline wiki pages."""

    def __init__(
        self,
        store: Any,
        tenant: str,
        project_id: str,
        *,
        read_only: bool = False,
    ) -> None:
        self._store = store
        self._tenant = tenant
        self._project_id = project_id
        self._read_only = read_only

    async def _list_dir(self, dir_path: str) -> list[VfsEntry]:
        return await self._store.list_dir(self._tenant, self._project_id, dir_path)

    async def _read_content(self, path: str) -> str | None:
        record = await self._store.read(self._tenant, self._project_id, path)
        return None if record is None else record.content

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        if self._read_only:
            raise PermissionError("wiki mount is read-only")
        await self._store.write(
            self._tenant, self._project_id, path, content, overwrite=overwrite
        )

    async def _glob_paths(self, pattern: str, base_path: str | None) -> list[str]:
        return await self._store.glob(
            self._tenant, self._project_id, pattern, base_path=base_path
        )

    async def _grep_matches(
        self,
        pattern: str,
        *,
        path_prefix: str | None,
        glob_filter: str | None,
    ) -> list[dict]:
        rows = await self._store.grep(
            self._tenant,
            self._project_id,
            pattern,
            path_prefix=path_prefix,
            glob_filter=glob_filter,
        )
        return [{"path": r.path, "line": r.line, "text": r.text} for r in rows]

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        if self._read_only:
            return WriteResult(error="wiki mount is read-only")
        return await super().awrite(file_path, content)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        if self._read_only:
            return EditResult(error="wiki mount is read-only")
        return await super().aedit(file_path, old_string, new_string, replace_all=replace_all)
