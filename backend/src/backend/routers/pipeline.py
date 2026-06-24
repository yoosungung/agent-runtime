from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from backend.pipeline_helpers import pg_settings_for_source, resolve_credential_secret
from backend.deps import check_csrf, get_settings, require_admin
from backend.pipeline_argo import submit_collect_ingest_rag, submit_ingest_rag
from backend.pipeline_cron import (
    delete_source_cron,
    reconcile_source_cron,
    validate_cron_schedule_or_http,
)
from backend.settings import Settings
from path_graph.admin.credentials import CredentialStore
from path_graph.admin.runner import manifest_lines_to_json, probe_source
from path_graph.admin.sources import SourceStore
from path_graph.admin.uploads import (
    UploadValidationError,
    build_ingest_manifest,
    list_documents_for_source,
    upload_raw_files,
)
from path_graph.contracts.source import SourceCreate, SourceDriver, SourceProfile, SourceUpdate
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


class SourceCreateRequest(BaseModel):
    name: str
    driver: SourceDriver
    source_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential_id: str | None = None
    enabled: bool = True
    schedule_cron: str | None = None


class SourceUpdateRequest(BaseModel):
    source_id: str | None = None
    config: dict[str, Any] | None = None
    credential_id: str | None = None
    enabled: bool | None = None
    schedule_cron: str | None = None


class SourceResponse(BaseModel):
    tenant: str
    id: str
    name: str
    driver: SourceDriver
    source_id: str
    config: dict[str, Any]
    credential_id: str | None = None
    enabled: bool
    schedule_cron: str | None = None
    last_batch_id: str | None = None
    last_run_at: str | None = None
    last_run_status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_profile(cls, profile: SourceProfile) -> SourceResponse:
        return cls(
            tenant=profile.tenant,
            id=profile.id,
            name=profile.name,
            driver=profile.driver,
            source_id=profile.source_id,
            config=profile.config,
            credential_id=profile.credential_id,
            enabled=profile.enabled,
            schedule_cron=profile.schedule_cron,
            last_batch_id=profile.last_batch_id,
            last_run_at=profile.last_run_at.isoformat() if profile.last_run_at else None,
            last_run_status=profile.last_run_status,
            created_at=profile.created_at.isoformat() if profile.created_at else None,
            updated_at=profile.updated_at.isoformat() if profile.updated_at else None,
        )


class SourcesListResponse(BaseModel):
    items: list[SourceResponse]


class TestSourceResponse(BaseModel):
    file_count: int
    sample_names: list[str]


class RunSourceResponse(BaseModel):
    batch_id: str
    manifest_key: str
    file_count: int | None = None
    workflow_name: str
    argo_uid: str


class UploadItemResponse(BaseModel):
    filename: str
    status: str
    skipped: bool | None = None
    reason: str | None = None
    content_hash: str | None = None
    document_id: str | None = None
    s3_raw_uri: str | None = None


class UploadFilesResponse(BaseModel):
    items: list[UploadItemResponse]
    uploaded_count: int
    skipped_count: int


class DocumentResponse(BaseModel):
    document_id: str
    source_id: str
    content_hash: str
    ingest_state: str
    s3_raw_uri: str
    filename: str


class DocumentsListResponse(BaseModel):
    items: list[DocumentResponse]


class IngestSourceRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)


def _require_manual_source(profile: SourceProfile) -> None:
    if profile.driver != SourceDriver.MANUAL:
        raise HTTPException(
            status_code=409,
            detail="upload and ingest are only supported for manual sources",
        )


async def _submit_ingest_for_manifest(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    source_uuid: str,
    profile: SourceProfile,
    batch_id: str,
    manifest_key: str,
    file_count: int,
) -> RunSourceResponse:
    if file_count == 0:
        await asyncio.to_thread(
            store.record_run,
            tenant,
            source_uuid,
            batch_id=batch_id,
            status="empty",
        )
        return RunSourceResponse(
            batch_id=batch_id,
            manifest_key=manifest_key,
            file_count=0,
            workflow_name="",
            argo_uid="",
        )

    manifest_json = await asyncio.to_thread(manifest_lines_to_json, manifest_key)
    argo = await submit_ingest_rag(
        settings=settings,
        tenant=tenant,
        batch_manifest_json=manifest_json,
        batch_manifest_key=manifest_key,
        source_name=profile.name,
    )
    run_id = str(uuid4())
    await asyncio.to_thread(
        store.record_run,
        tenant,
        source_uuid,
        batch_id=batch_id,
        status="submitted",
    )
    await asyncio.to_thread(
        store.insert_pipeline_run,
        tenant,
        run_id,
        argo["workflow_name"],
        batch_id,
        "submitted",
        argo.get("argo_uid"),
    )
    return RunSourceResponse(
        batch_id=batch_id,
        manifest_key=manifest_key,
        file_count=file_count,
        workflow_name=argo["workflow_name"],
        argo_uid=argo["argo_uid"],
    )


def _path_graph_dsn(settings: Settings) -> str:
    dsn = settings.PATH_GRAPH_DSN or settings.POSTGRES_DSN
    if not dsn:
        raise HTTPException(status_code=503, detail="PATH_GRAPH_DSN not configured")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _store(settings: Settings = Depends(get_settings)) -> SourceStore:  # noqa: B008
    return SourceStore(_path_graph_dsn(settings))


def _require_tenant(principal: Principal) -> str:
    tenant = (principal.tenant or "").strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="User tenant not set")
    return tenant


def _validate_schedule_cron(schedule_cron: str | None) -> None:
    if schedule_cron is not None and schedule_cron.strip():
        validate_cron_schedule_or_http(schedule_cron)


async def _sync_source_cron(
    request: Request,
    settings: Settings,
    profile: SourceProfile,
    dsn: str,
) -> None:
    if not (profile.schedule_cron or "").strip():
        await delete_source_cron(
            settings=settings,
            tenant=profile.tenant,
            source_id=profile.id,
        )
        return

    credential_secret = await resolve_credential_secret(
        request,
        settings,
        profile,
        dsn,
        require_connected=profile.enabled,
    )
    await reconcile_source_cron(
        settings=settings,
        tenant=profile.tenant,
        source_id=profile.id,
        schedule_cron=profile.schedule_cron,
        credential_secret=credential_secret,
        suspend=not profile.enabled,
    )


@router.get("/sources", dependencies=[Depends(require_admin)])
async def list_sources(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
) -> SourcesListResponse:
    tenant = _require_tenant(principal)
    profiles = await asyncio.to_thread(store.list_sources, tenant)
    return SourcesListResponse(items=[SourceResponse.from_profile(p) for p in profiles])


@router.post("/sources", status_code=201)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SourceResponse:
    tenant = _require_tenant(principal)
    _validate_schedule_cron(body.schedule_cron)
    create = SourceCreate(
        name=body.name,
        driver=body.driver,
        source_id=body.source_id,
        config=body.config,
        credential_id=body.credential_id,
        enabled=body.enabled,
        schedule_cron=body.schedule_cron,
    )
    try:
        profile = await asyncio.to_thread(store.create_source, tenant, create)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Source name already exists") from exc
    if profile.schedule_cron:
        await _sync_source_cron(request, settings, profile, _path_graph_dsn(settings))
    return SourceResponse.from_profile(profile)


@router.get("/sources/{source_id}", dependencies=[Depends(require_admin)])
async def get_source(
    source_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
) -> SourceResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceResponse.from_profile(profile)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str,
    body: SourceUpdateRequest,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SourceResponse:
    tenant = _require_tenant(principal)
    if body.schedule_cron is not None:
        _validate_schedule_cron(body.schedule_cron)
    update = SourceUpdate(
        source_id=body.source_id,
        config=body.config,
        credential_id=body.credential_id,
        enabled=body.enabled,
        schedule_cron=body.schedule_cron,
    )
    profile = await asyncio.to_thread(store.update_source, tenant, source_id, update)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    schedule_touched = body.schedule_cron is not None or body.enabled is not None
    credential_touched = body.credential_id is not None
    if schedule_touched or credential_touched or profile.schedule_cron:
        await _sync_source_cron(request, settings, profile, _path_graph_dsn(settings))
    return SourceResponse.from_profile(profile)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    tenant = _require_tenant(principal)
    deleted = await asyncio.to_thread(store.delete_source, tenant, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    await delete_source_cron(settings=settings, tenant=tenant, source_id=source_id)


@router.post("/sources/{source_id}/test")
async def test_source_endpoint(
    source_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> TestSourceResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        pg_settings = await pg_settings_for_source(
            request, settings, profile, _path_graph_dsn(settings)
        )
        result = await asyncio.to_thread(probe_source, profile, settings=pg_settings)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TestSourceResponse(**result)


@router.post("/sources/{source_id}/run", status_code=202)
async def run_source(
    source_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> RunSourceResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if not profile.enabled:
        raise HTTPException(status_code=400, detail="Source is disabled")
    if profile.driver == SourceDriver.MANUAL:
        raise HTTPException(
            status_code=409,
            detail="manual sources use upload and ingest endpoints, not run",
        )

    dsn = _path_graph_dsn(settings)
    credential_secret = await resolve_credential_secret(
        request, settings, profile, dsn, require_connected=True
    )
    if profile.credential_id:
        await pg_settings_for_source(request, settings, profile, dsn)

    batch_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    manifest_key = f"batches/{tenant}/{batch_id}/manifest.jsonl"

    argo = await submit_collect_ingest_rag(
        settings=settings,
        tenant=tenant,
        source_id=source_id,
        batch_id=batch_id,
        source_name=profile.name,
        credential_secret=credential_secret,
    )
    run_id = str(uuid4())
    await asyncio.to_thread(
        store.record_run,
        tenant,
        source_id,
        batch_id=batch_id,
        status="submitted",
    )
    await asyncio.to_thread(
        store.insert_pipeline_run,
        tenant,
        run_id,
        argo["workflow_name"],
        batch_id,
        "submitted",
        argo.get("argo_uid"),
    )
    return RunSourceResponse(
        batch_id=batch_id,
        manifest_key=manifest_key,
        file_count=None,
        workflow_name=argo["workflow_name"],
        argo_uid=argo["argo_uid"],
    )


@router.post("/sources/{source_id}/upload")
async def upload_source_files(
    source_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    files: list[UploadFile] = File(...),
) -> UploadFilesResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    _require_manual_source(profile)

    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    pg_settings = await pg_settings_for_source(
        request, settings, profile, _path_graph_dsn(settings)
    )
    payload: list[tuple[str, bytes, str]] = []
    for upload in files:
        data = await upload.read()
        filename = upload.filename or "upload.bin"
        mime = upload.content_type or "application/octet-stream"
        payload.append((filename, data, mime))

    try:
        result = await asyncio.to_thread(
            upload_raw_files,
            profile,
            payload,
            settings=pg_settings,
            server_max_mb=settings.MAX_PIPELINE_RAW_UPLOAD_MB,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UploadFilesResponse(**result)


@router.get("/sources/{source_id}/documents", dependencies=[Depends(require_admin)])
async def list_source_documents(
    source_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    ingest_state: str | None = None,
    limit: int = 50,
) -> DocumentsListResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")

    docs = await asyncio.to_thread(
        list_documents_for_source,
        tenant,
        profile,
        ingest_state=ingest_state,
        limit=limit,
        dsn=_path_graph_dsn(settings),
    )
    return DocumentsListResponse(items=[DocumentResponse(**d) for d in docs])


@router.post("/sources/{source_id}/ingest", status_code=202)
async def ingest_source_documents(
    source_id: str,
    body: IngestSourceRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> RunSourceResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if not profile.enabled:
        raise HTTPException(status_code=400, detail="Source is disabled")
    _require_manual_source(profile)

    document_ids = body.document_ids or None
    try:
        built = await asyncio.to_thread(
            build_ingest_manifest,
            profile,
            document_ids,
            dsn=_path_graph_dsn(settings),
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _submit_ingest_for_manifest(
        settings=settings,
        store=store,
        tenant=tenant,
        source_uuid=source_id,
        profile=profile,
        batch_id=built["batch_id"],
        manifest_key=built["manifest_key"],
        file_count=built["file_count"],
    )


@router.get("/runs", dependencies=[Depends(require_admin)])
async def list_runs(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    limit: int = 50,
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    runs = await asyncio.to_thread(store.list_pipeline_runs, tenant, limit)
    docs = await asyncio.to_thread(store.list_documents_summary, tenant, limit=20)
    return {"runs": runs, "recent_documents": docs}


@router.get("/dead-letters", dependencies=[Depends(require_admin)])
async def list_dead_letters(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    limit: int = 50,
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    items = await asyncio.to_thread(
        store.list_documents_summary,
        tenant,
        ingest_state="dead_letter",
        limit=limit,
    )
    return {"items": items}
