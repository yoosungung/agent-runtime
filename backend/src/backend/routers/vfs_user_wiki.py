"""Admin VFS routes for user and wiki scopes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.deps import check_csrf, get_db, get_principal, get_settings, require_admin
from backend.pipeline_domain import ProjectStore, api_get_binding
from backend.routers.pipeline import _project_store
from backend.routers.vfs import (
    VfsCreateFolderRequest,
    VfsEntriesListResponse,
    VfsEntryResponse,
    VfsFileResponse,
    VfsPatchFileRequest,
    VfsWriteFileRequest,
    _check_content_size,
    _entry_response,
    _validate_vfs_path,
)
from backend.settings import Settings
from runtime_common.db.models import UserRow
from runtime_common.schemas import Principal
from runtime_common.vfs.paths import normalize_dir
from runtime_common.vfs.store import MemoryUserVfsStore, UserVfsStore, VfsEntry
from runtime_common.vfs.wiki_store import MemoryWikiVfsStore, WikiVfsStore

router = APIRouter(
    prefix="/api/vfs",
    tags=["vfs"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


class VfsUserSummary(BaseModel):
    user_id: int
    username: str
    tenant: str
    file_count: int = 0
    total_bytes: int = 0
    last_modified: datetime | None = None


class VfsUsersListResponse(BaseModel):
    items: list[VfsUserSummary]
    total: int
    limit: int
    offset: int


class VfsWikiProjectSummary(BaseModel):
    project_id: str
    slug: str
    name: str
    vfs_mount: str
    file_count: int = 0
    total_bytes: int = 0
    last_modified: datetime | None = None


class VfsWikiProjectsListResponse(BaseModel):
    items: list[VfsWikiProjectSummary]
    total: int
    limit: int
    offset: int


def _get_user_store(request: Request) -> UserVfsStore:
    store = getattr(request.app.state, "vfs_user_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="VFS store not configured (set VFS_DSN)")
    return store


def _get_wiki_store(request: Request) -> WikiVfsStore:
    store = getattr(request.app.state, "vfs_wiki_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="VFS store not configured (set VFS_DSN)")
    return store


async def _fetch_user_vfs_stats(store: UserVfsStore) -> dict[int, dict[str, Any]]:
    if isinstance(store, MemoryUserVfsStore):
        out: dict[int, dict[str, Any]] = {}
        for (user_id, _path), row in store._rows.items():
            bucket = out.setdefault(
                user_id,
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
            SELECT user_id,
                   COUNT(*) FILTER (WHERE NOT is_dir) AS file_count,
                   COALESCE(SUM(CASE WHEN NOT is_dir THEN size ELSE 0 END), 0) AS total_bytes,
                   MAX(modified_at) AS last_modified
            FROM vfs_user_files
            GROUP BY user_id
            """
        )
    return {
        int(row["user_id"]): {
            "file_count": int(row["file_count"] or 0),
            "total_bytes": int(row["total_bytes"] or 0),
            "last_modified": row["last_modified"],
        }
        for row in rows
    }


def _check_wiki_content_size(content: str, settings: Settings) -> None:
    if len(content.encode("utf-8")) > settings.MAX_WIKI_VFS_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.MAX_WIKI_VFS_FILE_BYTES} byte limit",
        )


@router.get("/users", response_model=VfsUsersListResponse)
async def list_vfs_users(
    request: Request,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsUsersListResponse:
    limit = min(limit, 100)
    store = _get_user_store(request)
    stats = await _fetch_user_vfs_stats(store)
    result = await db.execute(select(UserRow).order_by(UserRow.username))
    users = list(result.scalars().all())
    total = len(users)
    page = users[offset : offset + limit]
    items = [
        VfsUserSummary(
            user_id=u.id,
            username=u.username,
            tenant=u.tenant,
            file_count=stats.get(u.id, {}).get("file_count", 0),
            total_bytes=stats.get(u.id, {}).get("total_bytes", 0),
            last_modified=stats.get(u.id, {}).get("last_modified"),
        )
        for u in page
    ]
    return VfsUsersListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/users/{user_id}/entries", response_model=VfsEntriesListResponse)
async def list_user_vfs_entries(
    user_id: int,
    request: Request,
    path: str = Query(default="/"),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsEntriesListResponse:
    user = await db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store = _get_user_store(request)
    entries = await store.list_dir(user_id, normalize_dir(_validate_vfs_path(path)))
    return VfsEntriesListResponse(items=[_entry_response(e) for e in entries])


@router.get("/users/{user_id}/files", response_model=VfsFileResponse)
async def read_user_vfs_file(
    user_id: int,
    request: Request,
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsFileResponse:
    user = await db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store = _get_user_store(request)
    norm = _validate_vfs_path(path)
    record = await store.read(user_id, norm)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.put("/users/{user_id}/files", response_model=VfsFileResponse, status_code=201)
async def create_user_vfs_file(
    user_id: int,
    body: VfsWriteFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    user = await db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store = _get_user_store(request)
    norm = _validate_vfs_path(body.path)
    _check_content_size(body.content, settings)
    try:
        await store.write(user_id, norm, body.content, overwrite=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = await store.read(user_id, norm)
    assert record is not None
    db.add(
        make_audit_row(
            "vfs.user.write",
            principal.user_id,
            principal.sub,
            target_user_id=user_id,
            path=norm,
            operation="create",
        )
    )
    await db.commit()
    log_event(
        "vfs.user.write",
        actor_id=principal.user_id,
        actor=principal.sub,
        target_user_id=user_id,
        path=norm,
        operation="create",
    )
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.patch("/users/{user_id}/files", response_model=VfsFileResponse)
async def patch_user_vfs_file(
    user_id: int,
    body: VfsPatchFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    user = await db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store = _get_user_store(request)
    norm = _validate_vfs_path(body.path)
    record = await store.read(user_id, norm)
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
    await store.write(user_id, norm, new_content, overwrite=True)
    updated = await store.read(user_id, norm)
    assert updated is not None
    db.add(
        make_audit_row(
            "vfs.user.write",
            principal.user_id,
            principal.sub,
            target_user_id=user_id,
            path=norm,
            operation="patch",
        )
    )
    await db.commit()
    log_event(
        "vfs.user.write",
        actor_id=principal.user_id,
        actor=principal.sub,
        target_user_id=user_id,
        path=norm,
        operation="patch",
    )
    return VfsFileResponse(
        path=updated.path,
        content=updated.content,
        encoding=updated.encoding,
        modified_at=updated.modified_at,
    )


@router.delete("/users/{user_id}/files", status_code=204)
async def delete_user_vfs_path(
    user_id: int,
    request: Request,
    path: str = Query(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    user = await db.get(UserRow, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    store = _get_user_store(request)
    norm = _validate_vfs_path(path)
    await store.delete(user_id, norm)
    db.add(
        make_audit_row(
            "vfs.user.delete",
            principal.user_id,
            principal.sub,
            target_user_id=user_id,
            path=norm,
        )
    )
    await db.commit()
    log_event(
        "vfs.user.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        target_user_id=user_id,
        path=norm,
    )


async def _get_wiki_project(store: ProjectStore, tenant: str, project_id: str):
    profile = await asyncio.to_thread(store.get_project, tenant, project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return profile


@router.get("/wiki/projects", response_model=VfsWikiProjectsListResponse)
async def list_wiki_vfs_projects(
    request: Request,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    settings: Settings = Depends(get_settings),  # noqa: B008
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsWikiProjectsListResponse:
    limit = min(limit, 100)
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    wiki_store = _get_wiki_store(request)
    profiles = await asyncio.to_thread(_project_store(settings).list_projects, tenant)
    total = len(profiles)
    page = profiles[offset : offset + limit]
    items: list[VfsWikiProjectSummary] = []
    for profile in page:
        if isinstance(wiki_store, MemoryWikiVfsStore):
            stats = {"file_count": 0, "total_bytes": 0, "last_modified": None}
        else:
            stats_obj = await wiki_store.project_stats(tenant, profile.id)
            stats = {
                "file_count": stats_obj.file_count,
                "total_bytes": stats_obj.total_bytes,
                "last_modified": stats_obj.last_modified,
            }
        binding = await asyncio.to_thread(api_get_binding, tenant, profile.id)
        mount = binding["wiki"]["vfs_mount"]
        items.append(
            VfsWikiProjectSummary(
                project_id=profile.id,
                slug=profile.slug,
                name=profile.name,
                vfs_mount=mount,
                file_count=stats["file_count"],
                total_bytes=stats["total_bytes"],
                last_modified=stats["last_modified"],
            )
        )
    return VfsWikiProjectsListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/wiki/projects/{project_id}/entries", response_model=VfsEntriesListResponse)
async def list_wiki_vfs_entries(
    project_id: str,
    request: Request,
    path: str = Query(default="/"),
    settings: Settings = Depends(get_settings),  # noqa: B008
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsEntriesListResponse:
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    await _get_wiki_project(_project_store(settings), tenant, project_id)
    store = _get_wiki_store(request)
    entries = await store.list_dir(
        tenant, project_id, normalize_dir(_validate_vfs_path(path))
    )
    return VfsEntriesListResponse(items=[_entry_response(e) for e in entries])


@router.get("/wiki/projects/{project_id}/files", response_model=VfsFileResponse)
async def read_wiki_vfs_file(
    project_id: str,
    request: Request,
    path: str = Query(...),
    settings: Settings = Depends(get_settings),  # noqa: B008
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> VfsFileResponse:
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    await _get_wiki_project(_project_store(settings), tenant, project_id)
    store = _get_wiki_store(request)
    norm = _validate_vfs_path(path)
    record = await store.read(tenant, project_id, norm)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.put("/wiki/projects/{project_id}/files", response_model=VfsFileResponse, status_code=201)
async def create_wiki_vfs_file(
    project_id: str,
    body: VfsWriteFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    await _get_wiki_project(_project_store(settings), tenant, project_id)
    store = _get_wiki_store(request)
    norm = _validate_vfs_path(body.path)
    _check_wiki_content_size(body.content, settings)
    try:
        await store.write(tenant, project_id, norm, body.content, overwrite=False)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = await store.read(tenant, project_id, norm)
    assert record is not None
    db.add(
        make_audit_row(
            "vfs.wiki.write",
            principal.user_id,
            principal.sub,
            project_id=project_id,
            path=norm,
            operation="create",
        )
    )
    await db.commit()
    log_event(
        "vfs.wiki.write",
        actor_id=principal.user_id,
        actor=principal.sub,
        project_id=project_id,
        path=norm,
        operation="create",
    )
    return VfsFileResponse(
        path=record.path,
        content=record.content,
        encoding=record.encoding,
        modified_at=record.modified_at,
    )


@router.patch("/wiki/projects/{project_id}/files", response_model=VfsFileResponse)
async def patch_wiki_vfs_file(
    project_id: str,
    body: VfsPatchFileRequest,
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> VfsFileResponse:
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    await _get_wiki_project(_project_store(settings), tenant, project_id)
    store = _get_wiki_store(request)
    norm = _validate_vfs_path(body.path)
    record = await store.read(tenant, project_id, norm)
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
    _check_wiki_content_size(new_content, settings)
    await store.write(tenant, project_id, norm, new_content, overwrite=True)
    updated = await store.read(tenant, project_id, norm)
    assert updated is not None
    db.add(
        make_audit_row(
            "vfs.wiki.write",
            principal.user_id,
            principal.sub,
            project_id=project_id,
            path=norm,
            operation="update",
        )
    )
    await db.commit()
    return VfsFileResponse(
        path=updated.path,
        content=updated.content,
        encoding=updated.encoding,
        modified_at=updated.modified_at,
    )


@router.delete("/wiki/projects/{project_id}/files", status_code=204)
async def delete_wiki_vfs_path(
    project_id: str,
    request: Request,
    path: str = Query(...),
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(status_code=400, detail="tenant required")
    await _get_wiki_project(_project_store(settings), tenant, project_id)
    store = _get_wiki_store(request)
    norm = _validate_vfs_path(path)
    await store.delete_tree(tenant, project_id, norm)
    db.add(
        make_audit_row(
            "vfs.wiki.delete",
            principal.user_id,
            principal.sub,
            project_id=project_id,
            path=norm,
        )
    )
    await db.commit()
