from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.bundle_ref_guard import assert_keys_not_in_use, ref_counts_for_keys
from backend.deps import check_csrf, get_db, get_principal, get_settings, require_admin
from backend.object_store_browser import BucketObjectItem, ObjectStoreBrowser
from backend.settings import Settings
from runtime_common.schemas import Principal

router = APIRouter(
    prefix="/api/bucket",
    tags=["bucket"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


class BucketInfoResponse(BaseModel):
    backend: Literal["local", "s3"]
    root_label: str
    bucket: str | None = None
    prefix: str | None = None
    endpoint: str | None = None


class BucketObjectItemResponse(BaseModel):
    key: str
    name: str
    kind: Literal["file", "folder"]
    size: int | None
    last_modified: datetime | None
    ref_count: int
    in_use: bool


class BucketListResponse(BaseModel):
    items: list[BucketObjectItemResponse]
    next_cursor: str | None = None


class CreateFolderRequest(BaseModel):
    parent_prefix: str = ""
    name: str


class DeleteObjectsRequest(BaseModel):
    keys: list[str] = Field(min_length=1)


class MoveObjectsRequest(BaseModel):
    sources: list[str] = Field(min_length=1)
    dest_prefix: str


class UploadResponse(BaseModel):
    key: str


class MoveResponse(BaseModel):
    keys: list[str]


class DownloadUrlResponse(BaseModel):
    url: str


def _get_browser(request: Request) -> ObjectStoreBrowser:
    browser = getattr(request.app.state, "object_store_browser", None)
    if browser is None:
        raise HTTPException(status_code=503, detail="Object store browser not initialized")
    return browser


def _attach_refs(
    items: list[BucketObjectItem],
    ref_counts: dict[str, int],
) -> list[BucketObjectItemResponse]:
    return [
        BucketObjectItemResponse(
            key=item.key,
            name=item.name,
            kind=item.kind,
            size=item.size,
            last_modified=item.last_modified,
            ref_count=ref_counts.get(item.key, 0),
            in_use=ref_counts.get(item.key, 0) > 0,
        )
        for item in items
    ]


@router.get("/info", response_model=BucketInfoResponse)
async def bucket_info(
    request: Request,
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> BucketInfoResponse:
    info = await _get_browser(request).info()
    return BucketInfoResponse(
        backend=info.backend,
        root_label=info.root_label,
        bucket=info.bucket,
        prefix=info.prefix,
        endpoint=info.endpoint,
    )


@router.get("/objects", response_model=BucketListResponse)
async def list_objects(
    request: Request,
    prefix: str = "",
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> BucketListResponse:
    browser = _get_browser(request)
    result = await browser.list_objects(prefix, cursor=cursor, limit=limit)
    file_keys = [item.key for item in result.items if item.kind == "file"]
    ref_counts = await ref_counts_for_keys(db, file_keys)
    return BucketListResponse(
        items=_attach_refs(result.items, ref_counts),
        next_cursor=result.next_cursor,
    )


@router.post("/folders", response_model=BucketObjectItemResponse, status_code=201)
async def create_folder(
    body: CreateFolderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> BucketObjectItemResponse:
    browser = _get_browser(request)
    key = await browser.create_folder(body.parent_prefix, body.name)
    db.add(make_audit_row("bucket.mkdir", principal.user_id, principal.sub, key=key))
    await db.commit()
    log_event("bucket.mkdir", actor_id=principal.user_id, actor=principal.sub, key=key)
    return BucketObjectItemResponse(
        key=key,
        name=body.name,
        kind="folder",
        size=None,
        last_modified=None,
        ref_count=0,
        in_use=False,
    )


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_object(
    request: Request,
    parent_prefix: str = Form(""),
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> UploadResponse:
    browser = _get_browser(request)
    max_bytes = settings.MAX_BUCKET_OBJECT_MB * 1024 * 1024
    key = await browser.upload(parent_prefix, file, max_bytes=max_bytes)
    db.add(make_audit_row("bucket.upload", principal.user_id, principal.sub, key=key))
    await db.commit()
    log_event("bucket.upload", actor_id=principal.user_id, actor=principal.sub, key=key)
    return UploadResponse(key=key)


@router.delete("/objects", status_code=204)
async def delete_objects(
    body: DeleteObjectsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    browser = _get_browser(request)
    expanded = await browser.expand_keys(body.keys)
    await assert_keys_not_in_use(db, expanded)
    await browser.delete_keys(body.keys)
    db.add(
        make_audit_row(
            "bucket.delete",
            principal.user_id,
            principal.sub,
            keys=body.keys,
        )
    )
    await db.commit()
    log_event(
        "bucket.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        keys=body.keys,
    )


@router.post("/move", response_model=MoveResponse)
async def move_objects(
    body: MoveObjectsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MoveResponse:
    browser = _get_browser(request)
    expanded = await browser.expand_keys(body.sources)
    await assert_keys_not_in_use(db, expanded)
    dest_keys = await browser.move(body.sources, body.dest_prefix)
    db.add(
        make_audit_row(
            "bucket.move",
            principal.user_id,
            principal.sub,
            sources=body.sources,
            dest_prefix=body.dest_prefix,
        )
    )
    await db.commit()
    log_event(
        "bucket.move",
        actor_id=principal.user_id,
        actor=principal.sub,
        sources=body.sources,
        dest_prefix=body.dest_prefix,
    )
    return MoveResponse(keys=dest_keys)


@router.get("/download-url", response_model=DownloadUrlResponse)
async def download_url(
    request: Request,
    key: str = Query(...),
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> DownloadUrlResponse:
    browser = _get_browser(request)
    url = await browser.download_url(key)
    return DownloadUrlResponse(url=url)


@router.get("/download")
async def download_file(
    request: Request,
    key: str = Query(...),
    settings: Settings = Depends(get_settings),  # noqa: B008
    _principal: Principal = Depends(require_admin),  # noqa: B008
) -> FileResponse:
    if settings.BUNDLE_STORAGE_BACKEND != "local":
        raise HTTPException(status_code=400, detail="Direct download only available in local mode")
    browser = _get_browser(request)
    url = await browser.download_url(key)
    if not url.startswith("/api/bucket/download?key="):
        raise HTTPException(status_code=500, detail="Unexpected download URL")
    from backend.object_store_browser import LocalObjectStoreBrowser

    if not isinstance(browser, LocalObjectStoreBrowser):
        raise HTTPException(status_code=500, detail="Invalid browser type")
    path = browser.file_path(key)
    return FileResponse(path=str(path), filename=key.split("/")[-1])
