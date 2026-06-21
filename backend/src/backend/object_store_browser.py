from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

import aiofiles
from fastapi import HTTPException, UploadFile

from backend.bucket_paths import (
    InvalidBucketPathError,
    basename,
    join_prefix,
    normalize_key,
    normalize_prefix,
)
from backend.bundle_storage import S3BundleStorage


@dataclass(frozen=True)
class BucketObjectItem:
    key: str
    name: str
    kind: Literal["file", "folder"]
    size: int | None
    last_modified: datetime | None
    ref_count: int = 0
    in_use: bool = False


@dataclass(frozen=True)
class BucketListResult:
    items: list[BucketObjectItem]
    next_cursor: str | None = None


@dataclass(frozen=True)
class BucketInfo:
    backend: Literal["local", "s3"]
    root_label: str
    bucket: str | None = None
    prefix: str | None = None
    endpoint: str | None = None


class ObjectStoreBrowser(Protocol):
    async def info(self) -> BucketInfo: ...

    async def list_objects(
        self,
        prefix: str = "",
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> BucketListResult: ...

    async def create_folder(self, parent_prefix: str, name: str) -> str: ...

    async def upload(
        self,
        parent_prefix: str,
        file: UploadFile,
        *,
        max_bytes: int,
    ) -> str: ...

    async def expand_keys(self, keys: list[str]) -> list[str]: ...

    async def delete_keys(self, keys: list[str]) -> None: ...

    async def move(self, sources: list[str], dest_prefix: str) -> list[str]: ...

    async def download_url(self, key: str) -> str: ...


def _map_path_error(exc: InvalidBucketPathError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


class LocalObjectStoreBrowser:
    """File-system object browser rooted at BUNDLE_STORAGE_DIR."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def _resolve(self, key: str) -> Path:
        try:
            normalized = normalize_key(key)
        except InvalidBucketPathError as exc:
            raise _map_path_error(exc) from exc
        rel = normalized.rstrip("/")
        if not rel:
            raise HTTPException(status_code=400, detail="Invalid path")
        target = (self._root / rel).resolve()
        if not str(target).startswith(str(self._root)):
            raise HTTPException(status_code=400, detail="Path escapes storage root")
        return target

    def _file_key(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    async def info(self) -> BucketInfo:
        return BucketInfo(backend="local", root_label=str(self._root))

    async def list_objects(
        self,
        prefix: str = "",
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> BucketListResult:
        try:
            dir_prefix = normalize_prefix(prefix)
        except InvalidBucketPathError as exc:
            raise _map_path_error(exc) from exc

        target_dir = self._root / dir_prefix if dir_prefix else self._root
        if not target_dir.exists() or not target_dir.is_dir():
            raise HTTPException(status_code=404, detail="Prefix not found")

        entries = sorted(
            target_dir.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        start = int(cursor) if cursor else 0
        page = entries[start : start + limit]
        items: list[BucketObjectItem] = []
        for entry in page:
            if entry.name == "tmp":
                continue
            if entry.is_dir():
                key = f"{dir_prefix}{entry.name}/"
                stat = entry.stat()
                items.append(
                    BucketObjectItem(
                        key=key,
                        name=entry.name,
                        kind="folder",
                        size=None,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )
            else:
                key = f"{dir_prefix}{entry.name}"
                stat = entry.stat()
                items.append(
                    BucketObjectItem(
                        key=key,
                        name=entry.name,
                        kind="file",
                        size=stat.st_size,
                        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    )
                )

        next_start = start + len(page)
        next_cursor = str(next_start) if next_start < len(entries) else None
        return BucketListResult(items=items, next_cursor=next_cursor)

    async def create_folder(self, parent_prefix: str, name: str) -> str:
        try:
            key = join_prefix(parent_prefix, name) + "/"
        except InvalidBucketPathError as exc:
            raise _map_path_error(exc) from exc
        path = self._resolve(key)
        if path.exists():
            raise HTTPException(status_code=409, detail="Folder already exists")
        path.mkdir(parents=True, exist_ok=False)
        return key

    async def upload(
        self,
        parent_prefix: str,
        file: UploadFile,
        *,
        max_bytes: int,
    ) -> str:
        filename = (file.filename or "upload").strip()
        if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid upload filename")
        try:
            key = join_prefix(parent_prefix, filename)
        except InvalidBucketPathError as exc:
            raise _map_path_error(exc) from exc
        dest = self._resolve(key)
        if dest.exists():
            raise HTTPException(status_code=409, detail="File already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)

        total = 0
        try:
            async with aiofiles.open(dest, "wb") as out:
                while True:
                    chunk = await file.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds maximum size of {max_bytes // (1024 * 1024)}MB",
                        )
                    await out.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        return key

    async def expand_keys(self, keys: list[str]) -> list[str]:
        expanded: list[str] = []
        for raw in keys:
            try:
                key = normalize_key(raw)
            except InvalidBucketPathError as exc:
                raise _map_path_error(exc) from exc
            path = self._resolve(key)
            if key.endswith("/"):
                if not path.exists():
                    raise HTTPException(status_code=404, detail=f"Folder not found: {key}")
                for child in sorted(path.rglob("*")):
                    if child.is_file():
                        expanded.append(self._file_key(child))
            else:
                if not path.exists():
                    raise HTTPException(status_code=404, detail=f"File not found: {key}")
                expanded.append(key)
        return expanded

    async def delete_keys(self, keys: list[str]) -> None:
        file_keys = await self.expand_keys(keys)
        for key in file_keys:
            path = self._resolve(key)
            path.unlink(missing_ok=True)
        for raw in keys:
            key = normalize_key(raw)
            if key.endswith("/"):
                path = self._resolve(key)
                if path.exists() and path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)

    async def move(self, sources: list[str], dest_prefix: str) -> list[str]:
        if not sources:
            raise HTTPException(status_code=400, detail="No sources provided")
        dest_keys: list[str] = []
        for src in sources:
            src_key = normalize_key(src)
            src_path = self._resolve(src_key)
            if not src_path.exists():
                raise HTTPException(status_code=404, detail=f"Source not found: {src_key}")

            if not dest_prefix.endswith("/") and len(sources) == 1:
                dest_key = normalize_key(dest_prefix) if dest_prefix.endswith("/") else dest_prefix.strip().lstrip("/")
            else:
                parent = normalize_prefix(dest_prefix)
                dest_key = f"{parent}{basename(src_key)}"

            dest_path = self._resolve(dest_key)
            if dest_path.exists():
                raise HTTPException(status_code=409, detail=f"Destination already exists: {dest_key}")
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dest_path))
            if src_key.endswith("/") and src_path.exists():
                shutil.rmtree(src_path, ignore_errors=True)
            dest_keys.append(dest_key)
        return dest_keys

    async def download_url(self, key: str) -> str:
        key = normalize_key(key)
        if key.endswith("/"):
            raise HTTPException(status_code=400, detail="Cannot download a folder")
        path = self._resolve(key)
        if not path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return f"/api/bucket/download?key={key}"

    def file_path(self, key: str) -> Path:
        return self._resolve(normalize_key(key))


class S3ObjectStoreBrowser:
    """S3 object browser scoped to a single bucket + prefix."""

    def __init__(self, storage: S3BundleStorage) -> None:
        self._storage = storage

    def _full_key(self, relative_key: str) -> str:
        try:
            normalized = normalize_key(relative_key) if relative_key.endswith("/") else normalize_key(relative_key)
        except InvalidBucketPathError as exc:
            raise _map_path_error(exc) from exc
        return f"{self._storage._prefix}{normalized}"

    def _relative_key(self, full_key: str) -> str:
        prefix = self._storage._prefix
        if not full_key.startswith(prefix):
            raise HTTPException(status_code=400, detail="Key outside storage prefix")
        return full_key[len(prefix) :]

    async def _client(self):
        import aioboto3  # noqa: PLC0415

        session = aioboto3.Session()
        return session.client("s3", **self._storage._client_kwargs())

    async def info(self) -> BucketInfo:
        return BucketInfo(
            backend="s3",
            root_label=f"{self._storage._bucket}/{self._storage._prefix}",
            bucket=self._storage._bucket,
            prefix=self._storage._prefix,
            endpoint=self._storage._endpoint_url,
        )

    async def list_objects(
        self,
        prefix: str = "",
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> BucketListResult:
        dir_prefix = normalize_prefix(prefix)
        full_prefix = f"{self._storage._prefix}{dir_prefix}"
        list_kwargs: dict = {
            "Bucket": self._storage._bucket,
            "Prefix": full_prefix,
            "Delimiter": "/",
            "MaxKeys": limit,
        }
        if cursor:
            list_kwargs["ContinuationToken"] = cursor
        async with await self._client() as s3:
            resp = await s3.list_objects_v2(**list_kwargs)

        items: list[BucketObjectItem] = []
        for cp in resp.get("CommonPrefixes") or []:
            rel = self._relative_key(cp["Prefix"])
            name = rel.rstrip("/").split("/")[-1]
            items.append(
                BucketObjectItem(
                    key=rel,
                    name=name,
                    kind="folder",
                    size=None,
                    last_modified=None,
                )
            )
        for obj in resp.get("Contents") or []:
            full_key = obj["Key"]
            if full_key == full_prefix.rstrip("/") + "/" or full_key.endswith("/"):
                continue
            rel = self._relative_key(full_key)
            if rel.endswith("/"):
                continue
            name = rel.split("/")[-1]
            items.append(
                BucketObjectItem(
                    key=rel,
                    name=name,
                    kind="file",
                    size=obj.get("Size"),
                    last_modified=obj.get("LastModified"),
                )
            )

        return BucketListResult(items=items, next_cursor=resp.get("NextContinuationToken"))

    async def create_folder(self, parent_prefix: str, name: str) -> str:
        key = join_prefix(parent_prefix, name) + "/"
        full_key = self._full_key(key)
        async with await self._client() as s3:
            await s3.put_object(Bucket=self._storage._bucket, Key=full_key, Body=b"")
        return key

    async def upload(
        self,
        parent_prefix: str,
        file: UploadFile,
        *,
        max_bytes: int,
    ) -> str:
        filename = (file.filename or "upload").strip()
        if not filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid upload filename")
        key = join_prefix(parent_prefix, filename)
        full_key = self._full_key(key)

        total = 0
        chunks: list[bytes] = []
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum size of {max_bytes // (1024 * 1024)}MB",
                )
            chunks.append(chunk)
        body = b"".join(chunks)

        async with await self._client() as s3:
            await s3.put_object(
                Bucket=self._storage._bucket,
                Key=full_key,
                Body=body,
                ContentType=file.content_type or "application/octet-stream",
            )
        return key

    async def _list_all_under(self, prefix: str) -> list[str]:
        full_prefix = self._full_key(prefix)
        keys: list[str] = []
        token: str | None = None
        async with await self._client() as s3:
            while True:
                kwargs = {
                    "Bucket": self._storage._bucket,
                    "Prefix": full_prefix,
                }
                if token:
                    kwargs["ContinuationToken"] = token
                resp = await s3.list_objects_v2(**kwargs)
                for obj in resp.get("Contents") or []:
                    rel = self._relative_key(obj["Key"])
                    if not rel.endswith("/"):
                        keys.append(rel)
                token = resp.get("NextContinuationToken")
                if not token:
                    break
        return keys

    async def expand_keys(self, keys: list[str]) -> list[str]:
        expanded: list[str] = []
        for raw in keys:
            key = normalize_key(raw)
            if key.endswith("/"):
                expanded.extend(await self._list_all_under(key))
            else:
                expanded.append(key)
        return expanded

    async def delete_keys(self, keys: list[str]) -> None:
        file_keys = await self.expand_keys(keys)
        if not file_keys and keys:
            return
        async with await self._client() as s3:
            for key in file_keys:
                await s3.delete_object(
                    Bucket=self._storage._bucket,
                    Key=self._full_key(key),
                )
            for raw in keys:
                key = normalize_key(raw)
                if key.endswith("/"):
                    await s3.delete_object(
                        Bucket=self._storage._bucket,
                        Key=self._full_key(key),
                    )

    async def move(self, sources: list[str], dest_prefix: str) -> list[str]:
        if not sources:
            raise HTTPException(status_code=400, detail="No sources provided")
        dest_keys: list[str] = []
        async with await self._client() as s3:
            for src in sources:
                src_key = normalize_key(src)
                file_keys = await self.expand_keys([src_key])
                if not file_keys and src_key.endswith("/"):
                    raise HTTPException(status_code=404, detail=f"Folder empty or not found: {src_key}")

                if not dest_prefix.endswith("/") and len(sources) == 1 and not src_key.endswith("/"):
                    dest_key = dest_prefix.strip().lstrip("/")
                else:
                    parent = normalize_prefix(dest_prefix)
                    dest_key = f"{parent}{basename(src_key)}"

                if src_key.endswith("/"):
                    folder_files = file_keys
                    src_folder = src_key
                    dest_folder = normalize_prefix(dest_key)
                    for fk in folder_files:
                        rel = fk[len(src_folder) :]
                        new_key = f"{dest_folder}{rel.lstrip('/')}"
                        copy_source = {"Bucket": self._storage._bucket, "Key": self._full_key(fk)}
                        await s3.copy_object(
                            Bucket=self._storage._bucket,
                            Key=self._full_key(new_key),
                            CopySource=copy_source,
                        )
                        await s3.delete_object(
                            Bucket=self._storage._bucket,
                            Key=self._full_key(fk),
                        )
                        dest_keys.append(new_key)
                    await s3.delete_object(
                        Bucket=self._storage._bucket,
                        Key=self._full_key(src_folder),
                    )
                else:
                    copy_source = {"Bucket": self._storage._bucket, "Key": self._full_key(src_key)}
                    await s3.copy_object(
                        Bucket=self._storage._bucket,
                        Key=self._full_key(dest_key),
                        CopySource=copy_source,
                    )
                    await s3.delete_object(
                        Bucket=self._storage._bucket,
                        Key=self._full_key(src_key),
                    )
                    dest_keys.append(dest_key)
        return dest_keys

    async def download_url(self, key: str) -> str:
        key = normalize_key(key)
        if key.endswith("/"):
            raise HTTPException(status_code=400, detail="Cannot download a folder")
        async with await self._client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._storage._bucket, "Key": self._full_key(key)},
                ExpiresIn=self._storage._presign_expiry,
            )


def make_object_store_browser(settings: object, bundle_storage: object) -> ObjectStoreBrowser:
    backend: str = getattr(settings, "BUNDLE_STORAGE_BACKEND", "local")
    if backend == "s3":
        if not isinstance(bundle_storage, S3BundleStorage):
            raise TypeError("S3 backend requires S3BundleStorage")
        return S3ObjectStoreBrowser(bundle_storage)
    root: str = getattr(settings, "BUNDLE_STORAGE_DIR", "/var/lib/admin/bundles")
    return LocalObjectStoreBrowser(root)
