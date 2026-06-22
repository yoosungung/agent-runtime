from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.deps import check_csrf, get_db, get_principal, get_settings, require_admin
from backend.settings import Settings
from runtime_common.db.models import SourceMetaRow
from runtime_common.schemas import Principal
from runtime_common.vfs.paths import normalize_dir, normalize_path
from runtime_common.vfs.store import (
    AgentVfsStore,
    MemoryAgentVfsStore,
    VfsEntry,
)

router = APIRouter(
    prefix="/api/vfs",
    tags=["vfs"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


class VfsAgentSummary(BaseModel):
    kind: str
    name: str
    version: str
    visibility: str
    retired: bool
    vfs_enabled: bool
    file_count: int = 0
    total_bytes: int = 0
    last_modified: datetime | None = None


class VfsAgentsListResponse(BaseModel):
    items: list[VfsAgentSummary]
    total: int
    limit: int
    offset: int


class VfsEntryResponse(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int
    modified_at: datetime | None = None


class VfsEntriesListResponse(BaseModel):
    items: list[VfsEntryResponse]


class VfsFileResponse(BaseModel):
    path: str
    content: str
    encoding: str
    modified_at: datetime | None = None


class VfsWriteFileRequest(BaseModel):
    path: str
    content: str = ""


class VfsPatchFileRequest(BaseModel):
    path: str
    content: str | None = None
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool = False


class VfsCreateFolderRequest(BaseModel):
    parent_path: str = "/"
    name: str


def _get_agent_store(request: Request) -> AgentVfsStore:
    store = getattr(request.app.state, "vfs_agent_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="VFS store not configured (set VFS_DSN)")
    return store


def _validate_vfs_path(path: str) -> str:
    if ".." in path.split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    return normalize_path(path)


def _vfs_enabled(config: dict[str, Any]) -> bool:
    general = config.get("general") or {}
    vfs = general.get("vfs") or {}
    return vfs.get("enabled", True)


async def _fetch_vfs_stats(store: AgentVfsStore) -> dict[tuple[str, str], dict[str, Any]]:
    """Return {(kind, name): {file_count, total_bytes, last_modified}}."""
    if isinstance(store, MemoryAgentVfsStore):
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for (kind, agent_name, _path), row in store._rows.items():
            key = (kind, agent_name)
            bucket = out.setdefault(
                key,
                {"file_count": 0, "total_bytes": 0, "last_modified": None},
            )
            if not row.is_dir:
                bucket["file_count"] += 1
                bucket["total_bytes"] += row.size
            if row.modified_at and (
                bucket["last_modified"] is None or row.modified_at > bucket["last_modified"]
            ):
                bucket["last_modified"] = row.modified_at
        return out

    pool = getattr(store, "_pool", None)
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kind, agent_name,
                   COUNT(*) FILTER (WHERE NOT is_dir) AS file_count,
                   COALESCE(SUM(CASE WHEN NOT is_dir THEN size ELSE 0 END), 0) AS total_bytes,
                   MAX(modified_at) AS last_modified
            FROM vfs_agent_files
            GROUP BY kind, agent_name
            """
        )
    return {
        (row["kind"], row["agent_name"]): {
            "file_count": int(row["file_count"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "last_modified": row["last_modified"],
        }
        for row in rows
    }


async def _latest_general_agents(
    db: AsyncSession,
    *,
    name_prefix: str | None,
    include_retired: bool,
) -> list[SourceMetaRow]:
    latest_version = (
        select(
            SourceMetaRow.kind,
            SourceMetaRow.name,
            func.max(SourceMetaRow.version).label("max_version"),
        )
        .where(SourceMetaRow.deploy_mode == "general", SourceMetaRow.kind == "agent")
        .group_by(SourceMetaRow.kind, SourceMetaRow.name)
        .subquery()
    )
    q = (
        select(SourceMetaRow)
        .join(
            latest_version,
            (SourceMetaRow.kind == latest_version.c.kind)
            & (SourceMetaRow.name == latest_version.c.name)
            & (SourceMetaRow.version == latest_version.c.max_version),
        )
        .where(SourceMetaRow.deploy_mode == "general", SourceMetaRow.kind == "agent")
    )
    if name_prefix:
        q = q.where(SourceMetaRow.name.startswith(name_prefix))
    if not include_retired:
        q = q.where(SourceMetaRow.retired.is_(False))
    q = q.order_by(SourceMetaRow.name)
    result = await db.execute(q)
    return list(result.scalars().all())


async def _get_general_agent_row(
    db: AsyncSession, kind: str, name: str
) -> SourceMetaRow | None:
    result = await db.execute(
        select(SourceMetaRow)
        .where(
            SourceMetaRow.deploy_mode == "general",
            SourceMetaRow.kind == kind,
            SourceMetaRow.name == name,
        )
        .order_by(SourceMetaRow.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _entry_response(entry: VfsEntry) -> VfsEntryResponse:
    return VfsEntryResponse(
        path=entry.path,
        name=entry.name,
        is_dir=entry.is_dir,
        size=entry.size,
        modified_at=entry.modified_at,
    )


def _check_content_size(content: str, settings: Settings) -> None:
    if len(content.encode("utf-8")) > settings.MAX_VFS_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.MAX_VFS_FILE_BYTES} byte limit",
        )


@router.get("/agents", response_model=VfsAgentsListResponse)
async def list_vfs_agents(
    request: Request,
    name: str | None = Query(default=None, description="Name prefix filter"),
    include_retired: bool = Query(default=False),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsAgentsListResponse:
    limit = min(limit, 100)
    store = _get_agent_store(request)
    rows = await _latest_general_agents(db, name_prefix=name or None, include_retired=include_retired)
    stats = await _fetch_vfs_stats(store)
    total = len(rows)
    page_rows = rows[offset : offset + limit]
    items = [
        VfsAgentSummary(
            kind=row.kind,
            name=row.name,
            version=row.version,
            visibility=row.visibility,
            retired=row.retired,
            vfs_enabled=_vfs_enabled(row.config),
            file_count=stats.get((row.kind, row.name), {}).get("file_count", 0),
            total_bytes=stats.get((row.kind, row.name), {}).get("total_bytes", 0),
            last_modified=stats.get((row.kind, row.name), {}).get("last_modified"),
        )
        for row in page_rows
    ]
    return VfsAgentsListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/agents/{kind}/{name}/entries", response_model=VfsEntriesListResponse)
async def list_vfs_entries(
    kind: str,
    name: str,
    request: Request,
    path: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsEntriesListResponse:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    store = _get_agent_store(request)
    dir_path = normalize_dir(_validate_vfs_path(path))
    entries = await store.list_dir(kind, name, dir_path)
    return VfsEntriesListResponse(items=[_entry_response(e) for e in entries])


@router.get("/agents/{kind}/{name}/files", response_model=VfsFileResponse)
async def read_vfs_file(
    kind: str,
    name: str,
    request: Request,
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsFileResponse:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    store = _get_agent_store(request)
    norm = _validate_vfs_path(path)
    record = await store.read(kind, name, norm)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.put("/agents/{kind}/{name}/files", response_model=VfsFileResponse, status_code=201)
async def create_vfs_file(
    kind: str,
    name: str,
    body: VfsWriteFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    store = _get_agent_store(request)
    norm = _validate_vfs_path(body.path)
    _check_content_size(body.content, settings)
    try:
        await store.write(kind, name, norm, body.content, overwrite=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = await store.read(kind, name, norm)
    assert record is not None
    db.add(
        make_audit_row(
            "vfs.agent.write",
            principal.user_id,
            principal.sub,
            kind=kind,
            agent_name=name,
            path=norm,
            operation="create",
        )
    )
    await db.commit()
    log_event(
        "vfs.agent.write",
        actor_id=principal.user_id,
        actor=principal.sub,
        kind=kind,
        agent_name=name,
        path=norm,
        operation="create",
    )
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.patch("/agents/{kind}/{name}/files", response_model=VfsFileResponse)
async def patch_vfs_file(
    kind: str,
    name: str,
    body: VfsPatchFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    store = _get_agent_store(request)
    norm = _validate_vfs_path(body.path)
    record = await store.read(kind, name, norm)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")

    if body.content is not None:
        new_content = body.content
    elif body.old_string is not None and body.new_string is not None:
        if body.replace_all:
            new_content = record.content.replace(body.old_string, body.new_string)
        else:
            if body.old_string not in record.content:
                raise HTTPException(status_code=400, detail="old_string not found in file")
            new_content = record.content.replace(body.old_string, body.new_string, 1)
    else:
        raise HTTPException(status_code=400, detail="Provide content or old_string/new_string")

    _check_content_size(new_content, settings)
    await store.write(kind, name, norm, new_content, overwrite=True)
    updated = await store.read(kind, name, norm)
    assert updated is not None
    db.add(
        make_audit_row(
            "vfs.agent.write",
            principal.user_id,
            principal.sub,
            kind=kind,
            agent_name=name,
            path=norm,
            operation="update",
        )
    )
    await db.commit()
    log_event(
        "vfs.agent.write",
        actor_id=principal.user_id,
        actor=principal.sub,
        kind=kind,
        agent_name=name,
        path=norm,
        operation="update",
    )
    return VfsFileResponse(
        path=updated.path,
        content=updated.content,
        encoding=updated.encoding,
        modified_at=updated.modified_at,
    )


@router.delete("/agents/{kind}/{name}/files", status_code=204)
async def delete_vfs_path(
    kind: str,
    name: str,
    request: Request,
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    store = _get_agent_store(request)
    norm = _validate_vfs_path(path)
    await store.delete_tree(kind, name, norm)
    db.add(
        make_audit_row(
            "vfs.agent.delete",
            principal.user_id,
            principal.sub,
            kind=kind,
            agent_name=name,
            path=norm,
        )
    )
    await db.commit()
    log_event(
        "vfs.agent.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        kind=kind,
        agent_name=name,
        path=norm,
    )


@router.post("/agents/{kind}/{name}/folders", response_model=VfsEntryResponse, status_code=201)
async def create_vfs_folder(
    kind: str,
    name: str,
    body: VfsCreateFolderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsEntryResponse:
    row = await _get_general_agent_row(db, kind, name)
    if row is None:
        raise HTTPException(status_code=404, detail="General agent not found")
    if not body.name or "/" in body.name or ".." in body.name:
        raise HTTPException(status_code=400, detail="Invalid folder name")
    parent = normalize_dir(_validate_vfs_path(body.parent_path))
    dir_path = normalize_dir(f"{parent.rstrip('/')}/{body.name}")
    store = _get_agent_store(request)
    await store.mkdir(kind, name, dir_path)
    entries = await store.list_dir(kind, name, parent)
    entry = next((e for e in entries if e.path == dir_path.rstrip("/") or e.path == dir_path), None)
    if entry is None:
        entry = VfsEntry(path=dir_path, name=body.name, is_dir=True, size=0, modified_at=None)
    db.add(
        make_audit_row(
            "vfs.agent.mkdir",
            principal.user_id,
            principal.sub,
            kind=kind,
            agent_name=name,
            path=dir_path,
        )
    )
    await db.commit()
    log_event(
        "vfs.agent.mkdir",
        actor_id=principal.user_id,
        actor=principal.sub,
        kind=kind,
        agent_name=name,
        path=dir_path,
    )
    return _entry_response(entry)
