"""Database-backed deepagents VFS backends."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING

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

from runtime_common.vfs.paths import (
    direct_children,
    format_read_content,
    glob_paths,
    grep_paths,
    normalize_path,
    utc_now_iso,
)
from runtime_common.vfs.store import AgentVfsStore, UserVfsStore

if TYPE_CHECKING:
    pass


def _run_async(coro):
    """Run a coroutine from sync or async caller context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class _DatabaseBackendBase(BackendProtocol):
    """Shared read/write/edit/glob/grep logic for database VFS backends."""

    async def _list_all_paths(self) -> list[str]:
        raise NotImplementedError

    async def _read_content(self, path: str) -> str | None:
        raise NotImplementedError

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        raise NotImplementedError

    async def als(self, path: str) -> LsResult:
        path = normalize_path(path)
        all_paths = await self._list_all_paths()
        entries = direct_children(all_paths, path)
        for entry in entries:
            if not entry.get("is_dir"):
                entry.setdefault("modified_at", utc_now_iso())
        return LsResult(entries=entries)

    def ls(self, path: str) -> LsResult:
        return _run_async(self.als(path))

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        file_path = normalize_path(file_path)
        content = await self._read_content(file_path)
        if content is None:
            return ReadResult(error=f"Error: File '{file_path}' not found")
        formatted = format_read_content(content, offset=offset, limit=limit)
        return ReadResult(file_data=FileData(content=formatted, encoding="utf-8"))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return _run_async(self.aread(file_path, offset=offset, limit=limit))

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

    def write(self, file_path: str, content: str) -> WriteResult:
        return _run_async(self.awrite(file_path, content))

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

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return _run_async(
            self.aedit(file_path, old_string, new_string, replace_all=replace_all)
        )

    async def _all_files_map(self) -> dict[str, str]:
        paths = await self._list_all_paths()
        files: dict[str, str] = {}
        for p in paths:
            content = await self._read_content(p)
            if content is not None:
                files[p] = content
        return files

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        all_paths = await self._list_all_paths()
        matched = glob_paths(all_paths, pattern, path)
        return GlobResult(matches=matched)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return _run_async(self.aglob(pattern, path))

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        files = await self._all_files_map()
        matches = grep_paths(files, pattern, path=path, glob_filter=glob)
        return GrepResult(matches=matches)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return _run_async(self.agrep(pattern, path=path, glob=glob))


class AgentDatabaseBackend(_DatabaseBackendBase):
    """Persistent VFS scoped by ``(kind, agent_name)`` — shared across users and versions."""

    def __init__(self, store: AgentVfsStore, kind: str, agent_name: str) -> None:
        self._store = store
        self._kind = kind
        self._agent_name = agent_name

    async def _list_all_paths(self) -> list[str]:
        return await self._store.list_paths(self._kind, self._agent_name)

    async def _read_content(self, path: str) -> str | None:
        record = await self._store.read(self._kind, self._agent_name, path)
        return None if record is None else record.content

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        await self._store.write(
            self._kind, self._agent_name, path, content, overwrite=overwrite
        )


class UserDatabaseBackend(_DatabaseBackendBase):
    """Persistent VFS scoped by ``user_id`` — personal cross-agent area."""

    def __init__(self, store: UserVfsStore, user_id: int) -> None:
        self._store = store
        self._user_id = user_id

    async def _list_all_paths(self) -> list[str]:
        return await self._store.list_paths(self._user_id)

    async def _read_content(self, path: str) -> str | None:
        record = await self._store.read(self._user_id, path)
        return None if record is None else record.content

    async def _write_content(self, path: str, content: str, *, overwrite: bool) -> None:
        await self._store.write(self._user_id, path, content, overwrite=overwrite)
