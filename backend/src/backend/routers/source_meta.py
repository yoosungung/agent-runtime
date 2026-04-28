from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.bundle_storage import BundleStorage, bundle_path
from backend.deps import check_csrf, get_db, get_settings, require_admin
from backend.settings import Settings
from runtime_common.db.models import SourceMetaRow, UserResourceAccessRow, UserRow
from runtime_common.schemas import AgentRuntimeKind, McpRuntimeKind

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/source-meta",
    tags=["source-meta"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_KINDS = {"agent", "mcp"}
VALID_RUNTIME_POOLS = {f"agent:{k}" for k in AgentRuntimeKind} | {
    f"mcp:{k}" for k in McpRuntimeKind
}

RE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
RE_VERSION = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
RE_ENTRYPOINT = re.compile(r"^[\w.]+:[\w]+$")
RE_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
RE_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
RE_SECRETS_REF = re.compile(r"^(vault|env|aws-sm)://.+$")

MAX_CONFIG_BYTES = 64 * 1024  # 64KB


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")


def _validate_runtime_pool(runtime_pool: str, kind: str) -> None:
    if runtime_pool not in VALID_RUNTIME_POOLS:
        raise HTTPException(
            status_code=400,
            detail=f"runtime_pool must be one of {sorted(VALID_RUNTIME_POOLS)}",
        )
    if not runtime_pool.startswith(f"{kind}:"):
        raise HTTPException(
            status_code=400,
            detail=f"runtime_pool prefix must match kind '{kind}'",
        )


def _validate_name(name: str) -> None:
    if not RE_NAME.match(name):
        raise HTTPException(
            status_code=400,
            detail="name must match ^[a-z0-9][a-z0-9-]{0,127}$",
        )


def _validate_version(version: str) -> None:
    if not RE_VERSION.match(version):
        raise HTTPException(
            status_code=400,
            detail="version must match ^[a-zA-Z0-9._-]{1,64}$",
        )


def _validate_entrypoint(entrypoint: str) -> None:
    if not RE_ENTRYPOINT.match(entrypoint):
        raise HTTPException(
            status_code=400,
            detail="entrypoint must match ^[\\w.]+:[\\w]+$",
        )


def _validate_checksum(checksum: str | None) -> None:
    if checksum is not None and not RE_CHECKSUM.match(checksum):
        raise HTTPException(
            status_code=400,
            detail="checksum must match ^sha256:[0-9a-f]{64}$",
        )


def _validate_config(config: dict | None) -> None:
    if config is None:
        return
    import json

    serialized = json.dumps(config)
    if len(serialized.encode()) > MAX_CONFIG_BYTES:
        raise HTTPException(status_code=413, detail="config exceeds 64KB limit")


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


class SourceMetaResponse(BaseModel):
    id: int
    kind: str
    name: str
    version: str
    runtime_pool: str
    entrypoint: str
    bundle_uri: str
    checksum: str | None
    sig_uri: str | None
    config: dict
    retired: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceMetaListResponse(BaseModel):
    items: list[SourceMetaResponse]
    total: int
    limit: int
    offset: int


def _row_to_response(row: SourceMetaRow) -> SourceMetaResponse:
    return SourceMetaResponse.model_validate(row)


# ---------------------------------------------------------------------------
# Source-meta access response
# ---------------------------------------------------------------------------


class AccessUserResponse(BaseModel):
    user_id: int
    username: str
    kind: str
    name: str
    created_at: datetime


class AccessListResponse(BaseModel):
    items: list[AccessUserResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# GET /api/source-meta
# ---------------------------------------------------------------------------


@router.get("", response_model=SourceMetaListResponse)
async def list_source_meta(
    kind: str | None = Query(None),
    name: str | None = Query(None, description="Name prefix filter"),
    retired: bool | None = Query(None),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SourceMetaListResponse:
    limit = min(limit, 100)
    q = select(SourceMetaRow)
    count_q = select(func.count()).select_from(SourceMetaRow)

    if kind is not None:
        q = q.where(SourceMetaRow.kind == kind)
        count_q = count_q.where(SourceMetaRow.kind == kind)
    if name is not None:
        q = q.where(SourceMetaRow.name.like(f"{name}%"))
        count_q = count_q.where(SourceMetaRow.name.like(f"{name}%"))
    if retired is not None:
        q = q.where(SourceMetaRow.retired == retired)
        count_q = count_q.where(SourceMetaRow.retired == retired)

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(SourceMetaRow.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.scalars().all()

    return SourceMetaListResponse(
        items=[_row_to_response(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /api/source-meta/{id}
# ---------------------------------------------------------------------------


@router.get("/{id}", response_model=SourceMetaResponse)
async def get_source_meta(
    id: int,
    db: AsyncSession = Depends(get_db),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/source-meta/bundle  (must be before /{id})
# ---------------------------------------------------------------------------


@router.post("/bundle", response_model=SourceMetaResponse, status_code=201)
async def upload_bundle(
    request: Request,
    file: UploadFile = File(..., description="Bundle zip file"),
    sig: UploadFile | None = File(None, description="Optional signature file"),
    meta: str = Form(..., description="JSON: {kind,name,version,runtime_pool,entrypoint,config?}"),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_admin),
) -> SourceMetaResponse:
    import json

    try:
        meta_dict: dict[str, Any] = json.loads(meta)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid meta JSON: {exc}") from exc

    kind = meta_dict.get("kind", "")
    name = meta_dict.get("name", "")
    version = meta_dict.get("version", "")
    runtime_pool = meta_dict.get("runtime_pool", "")
    entrypoint = meta_dict.get("entrypoint", "")
    config = meta_dict.get("config", {})

    _validate_kind(kind)
    _validate_name(name)
    _validate_version(version)
    _validate_runtime_pool(runtime_pool, kind)
    _validate_entrypoint(entrypoint)
    _validate_config(config)

    storage: BundleStorage = request.app.state.bundle_storage
    try:
        sha256_hex, bundle_uri = await storage.save_bundle(
            file, settings.MAX_BUNDLE_SIZE_MB, settings.MAX_DECOMPRESSED_MB
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    sig_uri: str | None = None
    if sig is not None:
        sig_uri = await storage.save_sig(sig, sha256_hex)

    checksum = f"sha256:{sha256_hex}"

    row = SourceMetaRow(
        kind=kind,
        name=name,
        version=version,
        runtime_pool=runtime_pool,
        entrypoint=entrypoint,
        bundle_uri=bundle_uri,
        checksum=checksum,
        sig_uri=sig_uri,
        config=config or {},
        retired=False,
    )
    db.add(row)
    db.add(
        make_audit_row(
            "source_meta.bundle_upload",
            principal.user_id,
            principal.sub,
            name=name,
            version=version,
        )
    )
    try:
        await db.flush()
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"source_meta (kind={kind}, name={name}, version={version}) already exists",
        ) from exc

    log_event(
        "source_meta.bundle_upload",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=row.id,
        name=name,
        version=version,
        checksum=checksum,
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/source-meta  (URI registration)
# ---------------------------------------------------------------------------


class SourceMetaCreateRequest(BaseModel):
    kind: str
    name: str
    version: str
    runtime_pool: str
    entrypoint: str
    bundle_uri: str
    checksum: str | None = None
    config: dict = {}


@router.post("", response_model=SourceMetaResponse, status_code=201)
async def create_source_meta(
    request: Request,
    body: SourceMetaCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_admin),
) -> SourceMetaResponse:
    _validate_kind(body.kind)
    _validate_name(body.name)
    _validate_version(body.version)
    _validate_runtime_pool(body.runtime_pool, body.kind)
    _validate_entrypoint(body.entrypoint)
    _validate_checksum(body.checksum)
    _validate_config(body.config)

    # Validate URI scheme
    uri_lower = body.bundle_uri.lower()
    valid_schemes = ("http://", "https://", "s3://", "oci://", "file://")
    if not any(uri_lower.startswith(s) for s in valid_schemes):
        raise HTTPException(
            status_code=400,
            detail="bundle_uri scheme must be one of: http, https, s3, oci, file",
        )

    checksum = body.checksum
    bundle_uri = body.bundle_uri

    # For http/https URIs: fetch, compute sha256, store locally
    if uri_lower.startswith("http://") or uri_lower.startswith("https://"):
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("GET", body.bundle_uri) as resp:
                    resp.raise_for_status()
                    sha256 = hashlib.sha256()
                    import uuid
                    from pathlib import Path

                    import aiofiles

                    tmp_path = Path(settings.BUNDLE_STORAGE_DIR) / "tmp" / f"{uuid.uuid4()}.zip"

                    max_bytes = settings.MAX_BUNDLE_SIZE_MB * 1024 * 1024
                    total = 0
                    async with aiofiles.open(tmp_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(65536):
                            total += len(chunk)
                            if total > max_bytes:
                                tmp_path.unlink(missing_ok=True)
                                raise HTTPException(
                                    status_code=413,
                                    detail=f"Remote bundle exceeds {settings.MAX_BUNDLE_SIZE_MB}MB",
                                )
                            sha256.update(chunk)
                            await f.write(chunk)

                    sha256_hex = sha256.hexdigest()
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Failed to fetch bundle URI: {exc}"
                ) from exc

        storage: BundleStorage = request.app.state.bundle_storage
        bundle_uri = await storage.commit_local_bundle(tmp_path, sha256_hex)
        checksum = f"sha256:{sha256_hex}"

    if checksum is None:
        raise HTTPException(
            status_code=400,
            detail="checksum is required for non-http bundle URIs (cannot fetch to compute)",
        )

    row = SourceMetaRow(
        kind=body.kind,
        name=body.name,
        version=body.version,
        runtime_pool=body.runtime_pool,
        entrypoint=body.entrypoint,
        bundle_uri=bundle_uri,
        checksum=checksum,
        sig_uri=None,
        config=body.config or {},
        retired=False,
    )
    db.add(row)
    db.add(
        make_audit_row(
            "source_meta.create",
            principal.user_id,
            principal.sub,
            kind=body.kind,
            name=body.name,
            version=body.version,
        )
    )
    try:
        await db.flush()
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"source_meta (kind={body.kind}, name={body.name}, version={body.version}) already exists",
        ) from exc

    log_event(
        "source_meta.create",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=row.id,
        kind=body.kind,
        name=body.name,
        version=body.version,
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/source-meta/{id}/signature
# ---------------------------------------------------------------------------


@router.post("/{id}/signature", response_model=SourceMetaResponse)
async def upload_signature(
    id: int,
    request: Request,
    sig: UploadFile = File(..., description="Signature file"),
    db: AsyncSession = Depends(get_db),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    checksum = row.checksum
    if not checksum or not checksum.startswith("sha256:"):
        raise HTTPException(status_code=400, detail="source_meta has no valid checksum")

    sha256_hex = checksum.removeprefix("sha256:")
    storage: BundleStorage = request.app.state.bundle_storage
    sig_uri = await storage.save_sig(sig, sha256_hex)
    row.sig_uri = sig_uri

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# PATCH /api/source-meta/{id}
# ---------------------------------------------------------------------------

ALLOWED_PATCH_FIELDS = {"entrypoint", "sig_uri", "runtime_pool", "config"}
REJECTED_PATCH_FIELDS = {
    "name",
    "version",
    "kind",
    "checksum",
    "bundle_uri",
    "retired",
    "created_at",
}


class SourceMetaPatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    entrypoint: str | None = None
    sig_uri: str | None = None
    runtime_pool: str | None = None
    config: dict | None = None


@router.patch("/{id}", response_model=SourceMetaResponse)
async def patch_source_meta(
    id: int,
    body: SourceMetaPatchRequest,
    db: AsyncSession = Depends(get_db),
    principal=Depends(require_admin),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    update_data = body.model_dump(exclude_none=True)

    if body.entrypoint is not None:
        _validate_entrypoint(body.entrypoint)
    if body.runtime_pool is not None:
        _validate_runtime_pool(body.runtime_pool, row.kind)
    if body.config is not None:
        _validate_config(body.config)

    for field, value in update_data.items():
        setattr(row, field, value)

    db.add(
        make_audit_row(
            "source_meta.patch",
            principal.user_id,
            principal.sub,
            id=id,
            changed_fields=list(update_data.keys()),
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(row)

    log_event(
        "source_meta.patch",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=id,
        changed_fields=list(update_data.keys()),
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/source-meta/{id}/retire
# ---------------------------------------------------------------------------


@router.post("/{id}/retire", response_model=SourceMetaResponse)
async def retire_source_meta(
    id: int,
    db: AsyncSession = Depends(get_db),
    principal=Depends(require_admin),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    row.retired = True
    db.add(make_audit_row("source_meta.retire", principal.user_id, principal.sub, id=id))
    await db.flush()
    await db.commit()
    await db.refresh(row)

    log_event(
        "source_meta.retire",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=id,
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# DELETE /api/source-meta/{id}
# ---------------------------------------------------------------------------


@router.delete("/{id}", status_code=204)
async def delete_source_meta(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_admin),
) -> None:
    if not settings.ALLOW_HARD_DELETE:
        raise HTTPException(
            status_code=403, detail="Hard delete not allowed (ALLOW_HARD_DELETE=false)"
        )

    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    checksum = row.checksum
    sha256_hex: str | None = None
    if checksum and checksum.startswith("sha256:"):
        sha256_hex = checksum.removeprefix("sha256:")

    db.add(make_audit_row("source_meta.delete", principal.user_id, principal.sub, id=id))
    await db.delete(row)
    await db.flush()

    # Check if other rows reference same checksum
    should_delete_files = False
    if sha256_hex:
        ref_count_result = await db.execute(
            select(func.count())
            .select_from(SourceMetaRow)
            .where(SourceMetaRow.checksum == checksum)
        )
        ref_count = ref_count_result.scalar_one()
        should_delete_files = ref_count == 0

    await db.commit()

    log_event(
        "source_meta.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=id,
    )

    if should_delete_files and sha256_hex:
        storage: BundleStorage = request.app.state.bundle_storage
        await storage.delete(sha256_hex)


# ---------------------------------------------------------------------------
# GET /api/source-meta/{id}/access
# ---------------------------------------------------------------------------


@router.get("/{id}/access", response_model=AccessListResponse)
async def get_source_meta_access(
    id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AccessListResponse:
    limit = min(limit, 100)

    # First get source_meta to extract name+kind
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    sm_kind = row.kind
    sm_name = row.name

    count_q = (
        select(func.count())
        .select_from(UserResourceAccessRow)
        .where(
            UserResourceAccessRow.kind == sm_kind,
            UserResourceAccessRow.name == sm_name,
        )
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = (
        select(
            UserResourceAccessRow.user_id,
            UserRow.username,
            UserResourceAccessRow.kind,
            UserResourceAccessRow.name,
            UserResourceAccessRow.created_at,
        )
        .join(UserRow, UserRow.id == UserResourceAccessRow.user_id)
        .where(
            UserResourceAccessRow.kind == sm_kind,
            UserResourceAccessRow.name == sm_name,
        )
        .order_by(UserRow.username.asc())
        .limit(limit)
        .offset(offset)
    )
    result2 = await db.execute(q)
    rows = result2.all()

    items = [
        AccessUserResponse(
            user_id=r.user_id,
            username=r.username,
            kind=r.kind,
            name=r.name,
            created_at=r.created_at,
        )
        for r in rows
    ]

    return AccessListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# POST /api/source-meta/{id}/verify
# ---------------------------------------------------------------------------


@router.post("/{id}/verify")
async def verify_bundle(
    id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    import hashlib as _hashlib

    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    if not row.bundle_uri or not row.bundle_uri.startswith("file://"):
        return {"verified": False, "error": "only file:// bundles can be verified"}

    if not row.checksum or not row.checksum.startswith("sha256:"):
        return {"verified": False, "error": "source_meta has no valid checksum"}

    expected_hex = row.checksum.removeprefix("sha256:")
    path = bundle_path(expected_hex, settings.BUNDLE_STORAGE_DIR)

    if not path.exists():
        return {"verified": False, "error": "bundle file not found on disk"}

    sha256 = _hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
    except OSError as exc:
        return {"verified": False, "error": f"failed to read bundle file: {exc}"}

    actual_hex = sha256.hexdigest()
    actual_checksum = f"sha256:{actual_hex}"

    if actual_hex == expected_hex:
        return {"verified": True, "checksum": actual_checksum}
    return {"verified": False, "error": "checksum mismatch"}
