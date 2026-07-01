"""Read-only S3 prefix backend for pipeline wiki mounts."""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Any

from deepagents.backends.protocol import (
    EditResult,
    FileData,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from runtime_common.vfs.paths import format_read_content, normalize_dir, normalize_path, utc_now_iso


class WikiS3ReadBackend:
    """Read-only deepagents backend for objects under an S3 prefix."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str,
        s3_client: Any,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._s3 = s3_client

    def _object_key(self, file_path: str) -> str:
        path = normalize_path(file_path).lstrip("/")
        return f"{self._prefix}{path}"

    def _list_sync(self, dir_path: str) -> list[dict]:
        prefix = self._object_key(normalize_dir(dir_path))
        paginator = self._s3.get_paginator("list_objects_v2")
        entries: dict[str, dict] = {}
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix, Delimiter="/"):
            for cp in page.get("CommonPrefixes", []):
                rel = cp["Prefix"][len(self._prefix) :].rstrip("/")
                name = rel.split("/")[-1] if rel else ""
                if name:
                    entries[name] = {"path": f"{normalize_dir(dir_path)}{name}/", "is_dir": True}
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix or key.endswith("/"):
                    continue
                rel = key[len(self._prefix) :]
                name = rel.split("/")[0]
                if "/" not in rel.rstrip("/"):
                    entries[name] = {
                        "path": normalize_path(f"{dir_path}/{name}"),
                        "is_dir": False,
                        "modified_at": utc_now_iso(),
                    }
        return list(entries.values())

    def _read_sync(self, file_path: str) -> str | None:
        key = self._object_key(file_path)
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read().decode("utf-8", errors="replace")
        except self._s3.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    async def als(self, path: str) -> LsResult:
        entries = await asyncio.to_thread(self._list_sync, path)
        return LsResult(entries=entries)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        content = await asyncio.to_thread(self._read_sync, file_path)
        if content is None:
            return ReadResult(error=f"Error: File '{file_path}' not found")
        formatted = format_read_content(content, offset=offset, limit=limit)
        return ReadResult(file_data=FileData(content=formatted, encoding="utf-8"))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error="wiki mount is read-only")

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        return EditResult(error="wiki mount is read-only")

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        base = normalize_dir(path)
        entries = await asyncio.to_thread(self._list_sync, base)
        paths = [e["path"] for e in entries if not e.get("is_dir")]
        matched = [p for p in paths if fnmatch.fnmatch(p, pattern)]
        return GlobResult(paths=matched)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return GrepResult(matches=[])

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        raise NotImplementedError("use async API")

    def write(self, file_path: str, content: str) -> WriteResult:
        raise NotImplementedError("use async API")

    def edit(self, file_path: str, old_string: str, new_string: str, *, replace_all: bool = False) -> EditResult:
        raise NotImplementedError("use async API")

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        raise NotImplementedError("use async API")

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        raise NotImplementedError("use async API")

    def ls(self, path: str) -> LsResult:
        raise NotImplementedError("use async API")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileData]:
        raise NotImplementedError("wiki mount is read-only")
