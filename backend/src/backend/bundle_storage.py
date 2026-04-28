from __future__ import annotations

import hashlib
import os
import uuid
import zipfile
from pathlib import Path
from typing import Protocol

import aiofiles
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Standalone helper functions (kept for backward-compat, used by LocalBundleStorage)
# ---------------------------------------------------------------------------


def ensure_dirs(storage_dir: str) -> None:
    """Create storage dir and tmp subdir if they don't exist."""
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    (Path(storage_dir) / "tmp").mkdir(parents=True, exist_ok=True)


async def save_bundle_file(
    file: UploadFile, storage_dir: str, max_mb: int, max_decompressed_mb: int = 500
) -> str:
    """Stream bundle zip to tmp, compute sha256, validate zip, atomic move.

    Returns sha256 hex string.
    Raises HTTPException(413) if compressed size too large, HTTPException(400) if invalid zip.
    Raises ValueError if decompressed size exceeds max_decompressed_mb.
    """
    max_bytes = max_mb * 1024 * 1024
    tmp_path = Path(storage_dir) / "tmp" / f"{uuid.uuid4()}.zip"

    sha256 = hashlib.sha256()
    total = 0

    try:
        async with aiofiles.open(tmp_path, "wb") as f:
            while True:
                chunk = await file.read(65536)  # 64KB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Bundle exceeds maximum size of {max_mb}MB",
                    )
                sha256.update(chunk)
                await f.write(chunk)
    except HTTPException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {exc}") from exc

    # Validate zip integrity and decompressed size
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ValueError(f"Bad file in zip: {bad}")
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > max_decompressed_mb * 1024 * 1024:
                tmp_path.unlink(missing_ok=True)
                raise ValueError(f"decompressed size exceeds limit of {max_decompressed_mb}MB")
    except ValueError:
        tmp_path.unlink(missing_ok=True)
        raise
    except (zipfile.BadZipFile, Exception) as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid zip file: {exc}") from exc

    checksum_hex = sha256.hexdigest()
    dest_path = bundle_path(checksum_hex, storage_dir)
    os.replace(tmp_path, dest_path)

    return checksum_hex


async def save_sig_file(file: UploadFile, sha256: str, storage_dir: str) -> None:
    """Save signature file atomically."""
    tmp_path = Path(storage_dir) / "tmp" / f"{uuid.uuid4()}.sig"

    try:
        async with aiofiles.open(tmp_path, "wb") as f:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                await f.write(chunk)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to read sig upload: {exc}") from exc

    dest_path = sig_path(sha256, storage_dir)
    os.replace(tmp_path, dest_path)


def bundle_path(sha256: str, storage_dir: str) -> Path:
    return Path(storage_dir) / f"{sha256}.zip"


def sig_path(sha256: str, storage_dir: str) -> Path:
    return Path(storage_dir) / f"{sha256}.sig"


def delete_files(sha256: str, storage_dir: str) -> None:
    """Delete .zip and .sig files if they exist."""
    bundle_path(sha256, storage_dir).unlink(missing_ok=True)
    sig_path(sha256, storage_dir).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# BundleStorage Protocol
# ---------------------------------------------------------------------------


class BundleStorage(Protocol):
    async def save_bundle(
        self, file: UploadFile, max_mb: int, max_decompressed_mb: int
    ) -> tuple[str, str]:
        """Stream upload, validate, store. Returns (sha256_hex, bundle_uri)."""
        ...

    async def save_sig(self, file: UploadFile, sha256: str) -> str:
        """Store signature file. Returns sig_uri."""
        ...

    async def commit_local_bundle(self, tmp_path: Path, sha256: str) -> str:
        """Move/upload a pre-downloaded local tmp file. Returns bundle_uri."""
        ...

    async def delete(self, sha256: str) -> None:
        """Delete bundle and sig."""
        ...

    async def serve_bundle(self, sha256: str) -> Response:
        """Return appropriate Response for serving the bundle file."""
        ...

    async def serve_sig(self, sha256: str) -> Response:
        """Return appropriate Response for serving the signature file."""
        ...

    async def ensure_ready(self) -> None:
        """Called during app startup (create dirs, verify S3 connection, etc.)."""
        ...


# ---------------------------------------------------------------------------
# LocalBundleStorage
# ---------------------------------------------------------------------------


class LocalBundleStorage:
    """File-system backed bundle storage. Wraps the standalone helper functions."""

    def __init__(self, storage_dir: str, base_url: str = "") -> None:
        self._storage_dir = storage_dir
        self._base_url = base_url.rstrip("/")

    def _bundle_uri(self, sha256_hex: str) -> str:
        if self._base_url:
            return f"{self._base_url}/{sha256_hex}.zip"
        return f"/bundles/{sha256_hex}.zip"

    def _sig_uri(self, sha256_hex: str) -> str:
        if self._base_url:
            return f"{self._base_url}/{sha256_hex}.sig"
        return f"/bundles/{sha256_hex}.sig"

    async def save_bundle(
        self, file: UploadFile, max_mb: int, max_decompressed_mb: int
    ) -> tuple[str, str]:
        sha256_hex = await save_bundle_file(file, self._storage_dir, max_mb, max_decompressed_mb)
        return sha256_hex, self._bundle_uri(sha256_hex)

    async def save_sig(self, file: UploadFile, sha256: str) -> str:
        await save_sig_file(file, sha256, self._storage_dir)
        return self._sig_uri(sha256)

    async def commit_local_bundle(self, tmp_path: Path, sha256: str) -> str:
        dest = bundle_path(sha256, self._storage_dir)
        os.replace(tmp_path, dest)
        return self._bundle_uri(sha256)

    async def delete(self, sha256: str) -> None:
        delete_files(sha256, self._storage_dir)

    async def serve_bundle(self, sha256: str) -> Response:
        file_path = bundle_path(sha256, self._storage_dir)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Bundle not found")
        return FileResponse(
            path=str(file_path),
            media_type="application/zip",
            filename=f"{sha256}.zip",
        )

    async def serve_sig(self, sha256: str) -> Response:
        file_path = sig_path(sha256, self._storage_dir)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Signature not found")
        return FileResponse(
            path=str(file_path),
            media_type="application/octet-stream",
            filename=f"{sha256}.sig",
        )

    async def ensure_ready(self) -> None:
        ensure_dirs(self._storage_dir)


# ---------------------------------------------------------------------------
# S3BundleStorage
# ---------------------------------------------------------------------------


class S3BundleStorage:
    """S3/MinIO backed bundle storage using aioboto3."""

    def __init__(
        self,
        bucket: str,
        prefix: str,
        endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
        presign_expiry: int,
        base_url: str = "",
        tmp_dir: str = "/tmp",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._endpoint_url = endpoint_url or None
        self._region = region
        self._access_key = access_key or None
        self._secret_key = secret_key or None
        self._presign_expiry = presign_expiry
        self._base_url = base_url.rstrip("/")
        self._tmp_dir = tmp_dir

    def _bundle_key(self, sha256_hex: str) -> str:
        return f"{self._prefix}{sha256_hex}.zip"

    def _sig_key(self, sha256_hex: str) -> str:
        return f"{self._prefix}{sha256_hex}.sig"

    def _bundle_uri(self, sha256_hex: str) -> str:
        if self._base_url:
            return f"{self._base_url}/{sha256_hex}.zip"
        return f"/bundles/{sha256_hex}.zip"

    def _sig_uri(self, sha256_hex: str) -> str:
        if self._base_url:
            return f"{self._base_url}/{sha256_hex}.sig"
        return f"/bundles/{sha256_hex}.sig"

    def _client_kwargs(self) -> dict:
        from botocore.config import Config  # noqa: PLC0415

        kwargs: dict = {
            "region_name": self._region,
            # NCP Object Storage (and other S3-compatible backends) reject
            # boto3 1.36+ default checksum trailers (aws-chunked + x-amz-trailer)
            # with 403 AccessDenied. Opt out unless the caller explicitly asks.
            "config": Config(
                signature_version="s3v4",
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        }
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        if self._access_key and self._secret_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key
        return kwargs

    async def _upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        """Upload a local file to S3 using put_object."""
        import aioboto3  # noqa: PLC0415

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            async with aiofiles.open(local_path, "rb") as f:
                data = await f.read()
            await s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

    async def save_bundle(
        self, file: UploadFile, max_mb: int, max_decompressed_mb: int
    ) -> tuple[str, str]:
        """Stream to tmp, validate, upload to S3, delete tmp."""
        max_bytes = max_mb * 1024 * 1024
        tmp_path = Path(self._tmp_dir) / f"{uuid.uuid4()}.zip"

        sha256 = hashlib.sha256()
        total = 0

        try:
            async with aiofiles.open(tmp_path, "wb") as f:
                while True:
                    chunk = await file.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Bundle exceeds maximum size of {max_mb}MB",
                        )
                    sha256.update(chunk)
                    await f.write(chunk)
        except HTTPException:
            tmp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"Failed to read upload: {exc}") from exc

        # Validate zip integrity and decompressed size
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise ValueError(f"Bad file in zip: {bad}")
                total_uncompressed = sum(info.file_size for info in zf.infolist())
                if total_uncompressed > max_decompressed_mb * 1024 * 1024:
                    tmp_path.unlink(missing_ok=True)
                    raise ValueError(f"decompressed size exceeds limit of {max_decompressed_mb}MB")
        except ValueError:
            tmp_path.unlink(missing_ok=True)
            raise
        except (zipfile.BadZipFile, Exception) as exc:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"Invalid zip file: {exc}") from exc

        sha256_hex = sha256.hexdigest()

        try:
            await self._upload_file(tmp_path, self._bundle_key(sha256_hex), "application/zip")
        finally:
            tmp_path.unlink(missing_ok=True)

        return sha256_hex, self._bundle_uri(sha256_hex)

    async def save_sig(self, file: UploadFile, sha256: str) -> str:
        """Upload signature directly to S3."""
        import aioboto3  # noqa: PLC0415

        # Read sig content
        chunks = []
        try:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Failed to read sig upload: {exc}"
            ) from exc

        data = b"".join(chunks)

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=self._sig_key(sha256),
                Body=data,
                ContentType="application/octet-stream",
            )

        return self._sig_uri(sha256)

    async def commit_local_bundle(self, tmp_path: Path, sha256: str) -> str:
        """Upload a pre-downloaded tmp file to S3, then delete it."""
        try:
            await self._upload_file(tmp_path, self._bundle_key(sha256), "application/zip")
        finally:
            tmp_path.unlink(missing_ok=True)
        return self._bundle_uri(sha256)

    async def delete(self, sha256: str) -> None:
        """Delete .zip and .sig from S3."""
        import aioboto3  # noqa: PLC0415

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            # Delete both objects; ignore errors if they don't exist
            for key in [self._bundle_key(sha256), self._sig_key(sha256)]:
                try:
                    await s3.delete_object(Bucket=self._bucket, Key=key)
                except Exception:
                    pass

    async def serve_bundle(self, sha256: str) -> Response:
        """Generate presigned URL and redirect."""
        import aioboto3  # noqa: PLC0415

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._bundle_key(sha256)},
                ExpiresIn=self._presign_expiry,
            )
        return RedirectResponse(url=url, status_code=307)

    async def serve_sig(self, sha256: str) -> Response:
        """Generate presigned URL and redirect."""
        import aioboto3  # noqa: PLC0415

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._sig_key(sha256)},
                ExpiresIn=self._presign_expiry,
            )
        return RedirectResponse(url=url, status_code=307)

    async def ensure_ready(self) -> None:
        """Verify S3 bucket is accessible at startup."""
        import aioboto3  # noqa: PLC0415

        try:
            session = aioboto3.Session()
            async with session.client("s3", **self._client_kwargs()) as s3:
                await s3.head_bucket(Bucket=self._bucket)
        except Exception as exc:
            raise RuntimeError(f"S3 bucket '{self._bucket}' not accessible: {exc}") from exc


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_bundle_storage(settings: object) -> BundleStorage:
    """Create a BundleStorage from settings."""
    backend: str = getattr(settings, "BUNDLE_STORAGE_BACKEND", "local")

    if backend == "s3":
        bucket: str = getattr(settings, "S3_BUCKET", "")
        prefix: str = getattr(settings, "S3_PREFIX", "bundles/")
        endpoint_url: str = getattr(settings, "S3_ENDPOINT_URL", "")
        region: str = getattr(settings, "S3_REGION", "us-east-1")
        access_key: str = getattr(settings, "S3_ACCESS_KEY_ID", "")
        secret_key: str = getattr(settings, "S3_SECRET_ACCESS_KEY", "")
        presign_expiry: int = getattr(settings, "S3_PRESIGN_EXPIRY_SEC", 3600)

        base_url: str = getattr(settings, "BUNDLE_PUBLIC_BASE_URL", "")
        return S3BundleStorage(
            bucket=bucket,
            prefix=prefix,
            endpoint_url=endpoint_url or None,
            region=region,
            access_key=access_key or None,
            secret_key=secret_key or None,
            presign_expiry=presign_expiry,
            base_url=base_url,
        )

    # Default: local
    storage_dir: str = getattr(settings, "BUNDLE_STORAGE_DIR", "/var/lib/admin/bundles")
    base_url: str = getattr(settings, "BUNDLE_PUBLIC_BASE_URL", "")
    return LocalBundleStorage(storage_dir=storage_dir, base_url=base_url)
