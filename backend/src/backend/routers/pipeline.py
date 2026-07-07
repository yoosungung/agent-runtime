from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from backend.pipeline_domain import (
    DownstreamBusyError,
    DownstreamValidationError,
    LIFECYCLE_BATCH_ID,
    PgMetaStore,
    PgSettings,
    ProjectCreate,
    ProjectLifecycleBusyError,
    ProjectProfile,
    ProjectStore,
    SourceCreate,
    SourceDriver,
    SourceProfile,
    SourceStore,
    SourceUpdate,
    UploadValidationError,
    api_cleanup_project,
    api_get_binding,
    api_list_tombstones,
    api_purge_document,
    api_purge_source,
    api_reconcile_project,
    api_reingest_document,
    api_restore_document,
    api_search_project,
    assert_project_graphrag_idle,
    assert_project_lifecycle_idle,
    build_ingest_manifest,
    count_documents_for_project,
    count_documents_for_source,
    filename_from_raw_uri,
    list_documents_for_project,
    list_documents_for_source,
    make_blob_store,
    mark_project_lifecycle_started,
    prepare_graphrag_submission,
    probe_source,
    s3_key_dead_letter,
    upload_raw_files,
)
from pydantic import BaseModel, Field

from backend.deps import check_csrf, get_settings, require_admin
from backend.pipeline_argo import (
    submit_collect_ingest_rag,
    submit_delete_project,
    submit_graphrag,
    submit_ingest_rag,
    submit_purge_project,
)
from backend.pipeline_cron import (
    delete_project_reconcile_cron,
    delete_source_cron,
    reconcile_project_cron,
    reconcile_source_cron,
    validate_cron_schedule_or_http,
)
from backend.pipeline_helpers import (
    assert_source_ingest_idle,
    assert_source_workflow_idle,
    enrich_pipeline_runs_with_argo,
    get_source_workflow_status,
    pg_settings_for_source,
    pipeline_blob_settings,
    resolve_credential_secret,
)
from backend.settings import Settings
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


def _clamp_page_limit(limit: int, maximum: int = 100) -> int:
    return min(max(limit, 1), maximum)


class PaginatedResponse(BaseModel):
    total: int
    limit: int
    offset: int


class ProjectCreateRequest(BaseModel):
    name: str
    slug: str | None = None


class ProjectResponse(BaseModel):
    tenant: str
    id: str
    slug: str
    name: str
    created_at: str | None = None

    @classmethod
    def from_profile(cls, profile: ProjectProfile) -> ProjectResponse:
        return cls(
            tenant=profile.tenant,
            id=profile.id,
            slug=profile.slug,
            name=profile.name,
            created_at=profile.created_at.isoformat() if profile.created_at else None,
        )


class ProjectsListResponse(BaseModel):
    items: list[ProjectResponse]


class SourceCreateRequest(BaseModel):
    project_id: str
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
    project_id: str
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
            project_id=profile.project_id,
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


class SourcesListResponse(PaginatedResponse):
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


class RunSourceRequest(BaseModel):
    sync_mode: str = Field(
        default="full",
        description="Collect override: full (Run now default) or delta",
    )
class SourceWorkflowStatusResponse(BaseModel):
    active: bool
    workflow_name: str | None = None
    phase: str | None = None
    batch_id: str | None = None
    last_run_status: str | None = None
    argo_available: bool = True


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
    project_id: str | None = None
    content_hash: str
    ingest_state: str
    s3_raw_uri: str
    filename: str


class DocumentDetailResponse(DocumentResponse):
    dead_letter_error: dict[str, Any] | None = None


class DocumentsListResponse(PaginatedResponse):
    items: list[DocumentResponse]


class TombstonesListResponse(BaseModel):
    items: list[dict[str, Any]]


class RunsListResponse(PaginatedResponse):
    items: list[dict[str, Any]]
    argo_available: bool = True


class PurgeDocumentRequest(BaseModel):
    reason: str | None = None
    hard_raw: bool = False


class GraphragSubmitRequest(BaseModel):
    batch_id: str


class GraphragSubmitResponse(BaseModel):
    batch_id: str
    chunks_key: str
    document_count: int
    workflow_name: str
    workflow_template: str
    argo_uid: str


class ProjectLifecycleSubmitResponse(BaseModel):
    workflow_name: str
    workflow_template: str
    argo_uid: str
    run_kind: str


class PurgeReasonRequest(BaseModel):
    reason: str | None = None


class CleanupRequest(BaseModel):
    dry_run: bool = True


class IngestSourceRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)


def _read_dead_letter_error(
    tenant: str, content_hash: str, pg_settings: PgSettings
) -> dict[str, Any] | None:
    key = s3_key_dead_letter(tenant, content_hash)
    blob = make_blob_store(pg_settings)
    if not blob.exists(key):
        return None
    try:
        return json.loads(blob.get_bytes(key).decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


async def _require_project(
    tenant: str, project_id: str, store: ProjectStore
) -> ProjectProfile:
    profile = await asyncio.to_thread(store.get_project, tenant, project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return profile


async def _submit_project_lifecycle(
    *,
    operation: str,
    tenant: str,
    project: ProjectProfile,
    reason: str | None,
    settings: Settings,
    source_store: SourceStore,
    project_store: ProjectStore,
) -> ProjectLifecycleSubmitResponse:
    try:
        await asyncio.to_thread(
            assert_project_lifecycle_idle,
            project_store,
            source_store,
            tenant,
            project.id,
            operation=operation,
        )
    except ProjectLifecycleBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await asyncio.to_thread(
        mark_project_lifecycle_started,
        project_store,
        tenant,
        project.id,
        operation=operation,
    )
    submit = submit_purge_project if operation == "purge" else submit_delete_project
    template = (
        settings.PATH_GRAPH_PURGE_PROJECT_WF_TEMPLATE
        if operation == "purge"
        else settings.PATH_GRAPH_DELETE_PROJECT_WF_TEMPLATE
    )
    argo = await submit(
        settings=settings,
        tenant=tenant,
        project_id=project.id,
        project_slug=project.slug,
        reason=reason or "",
    )
    run_id = str(uuid4())
    await asyncio.to_thread(
        source_store.insert_pipeline_run,
        tenant,
        run_id,
        argo["workflow_name"],
        LIFECYCLE_BATCH_ID[operation],
        "submitted",
        argo.get("argo_uid"),
        project_id=project.id,
        run_kind=operation,
    )
    return ProjectLifecycleSubmitResponse(
        workflow_name=argo["workflow_name"],
        workflow_template=template,
        argo_uid=argo["argo_uid"],
        run_kind=operation,
    )


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

    argo = await submit_ingest_rag(
        settings=settings,
        tenant=tenant,
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
        project_id=profile.project_id,
        run_kind="ingest",
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


def _project_store(settings: Settings = Depends(get_settings)) -> ProjectStore:  # noqa: B008
    return ProjectStore(_path_graph_dsn(settings))


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


async def _sync_project_reconcile_cron(
    settings: Settings,
    tenant: str,
    project_id: str,
) -> None:
    try:
        await reconcile_project_cron(
            settings=settings,
            tenant=tenant,
            project_id=project_id,
        )
    except HTTPException as exc:
        logger.warning(
            "project_reconcile_cron.sync_failed",
            extra={"tenant": tenant, "project_id": project_id, "status": exc.status_code},
        )


async def _delete_project_reconcile_cron_safe(
    settings: Settings,
    tenant: str,
    project_id: str,
) -> None:
    try:
        await delete_project_reconcile_cron(
            settings=settings,
            tenant=tenant,
            project_id=project_id,
        )
    except HTTPException as exc:
        logger.warning(
            "project_reconcile_cron.delete_failed",
            extra={"tenant": tenant, "project_id": project_id, "status": exc.status_code},
        )


@router.get("/projects", dependencies=[Depends(require_admin)])
async def list_projects(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> ProjectsListResponse:
    tenant = _require_tenant(principal)
    profiles = await asyncio.to_thread(store.list_projects, tenant)
    return ProjectsListResponse(items=[ProjectResponse.from_profile(p) for p in profiles])


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ProjectResponse:
    tenant = _require_tenant(principal)
    create = ProjectCreate(name=body.name, slug=body.slug)
    try:
        profile = await asyncio.to_thread(store.create_project, tenant, create)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Project slug already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _sync_project_reconcile_cron(settings, tenant, profile.id)
    return ProjectResponse.from_profile(profile)


@router.get("/projects/{project_id}", dependencies=[Depends(require_admin)])
async def get_project(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> ProjectResponse:
    tenant = _require_tenant(principal)
    profile = await _require_project(tenant, project_id, store)
    return ProjectResponse.from_profile(profile)


@router.get("/projects/{project_id}/binding", dependencies=[Depends(require_admin)])
async def get_project_binding(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    try:
        return await asyncio.to_thread(api_get_binding, tenant, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/search", dependencies=[Depends(require_admin)])
async def search_project(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
    q: str = Query(..., min_length=1),
    top_k: int = Query(10, ge=1, le=50),
    mode: str = Query("auto"),
    include_graph: bool = Query(False),
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    try:
        return await asyncio.to_thread(
            api_search_project,
            tenant,
            project_id,
            q,
            top_k=top_k,
            mode=mode,
            include_graph=include_graph,
        )
    except ValueError as exc:
        msg = str(exc)
        if "project not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc


@router.get("/projects/{project_id}/documents", dependencies=[Depends(require_admin)])
async def list_project_documents(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    source_id: str | None = None,
    ingest_state: str | None = None,
    filename: str | None = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> DocumentsListResponse:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    limit = _clamp_page_limit(limit)
    dsn = _path_graph_dsn(settings)
    total = await asyncio.to_thread(
        count_documents_for_project,
        tenant,
        project_id,
        source_id=source_id,
        ingest_state=ingest_state,
        filename_contains=filename or None,
        dsn=dsn,
    )
    docs = await asyncio.to_thread(
        list_documents_for_project,
        tenant,
        project_id,
        source_id=source_id,
        ingest_state=ingest_state,
        filename_contains=filename or None,
        limit=limit,
        offset=offset,
        dsn=dsn,
    )
    return DocumentsListResponse(
        items=[DocumentResponse(**d) for d in docs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/tombstones", dependencies=[Depends(require_admin)])
async def list_project_tombstones(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> TombstonesListResponse:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    items = await asyncio.to_thread(api_list_tombstones, tenant, project_id=project_id)
    return TombstonesListResponse(items=items)


@router.post("/projects/{project_id}/reconcile")
async def reconcile_project(
    project_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    return await asyncio.to_thread(api_reconcile_project, tenant, project_id)


@router.post("/projects/{project_id}/cleanup")
async def cleanup_project(
    project_id: str,
    body: CleanupRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: ProjectStore = Depends(_project_store),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, store)
    return await asyncio.to_thread(
        api_cleanup_project, tenant, project_id, dry_run=body.dry_run
    )


@router.post("/projects/{project_id}/purge", status_code=202)
async def purge_project_endpoint(
    project_id: str,
    body: PurgeReasonRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    project_store: ProjectStore = Depends(_project_store),  # noqa: B008
    source_store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ProjectLifecycleSubmitResponse:
    tenant = _require_tenant(principal)
    project = await _require_project(tenant, project_id, project_store)
    return await _submit_project_lifecycle(
        operation="purge",
        tenant=tenant,
        project=project,
        reason=body.reason,
        settings=settings,
        source_store=source_store,
        project_store=project_store,
    )


@router.post("/projects/{project_id}/delete", status_code=202)
async def delete_project_endpoint(
    project_id: str,
    body: PurgeReasonRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    project_store: ProjectStore = Depends(_project_store),  # noqa: B008
    source_store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ProjectLifecycleSubmitResponse:
    tenant = _require_tenant(principal)
    project = await _require_project(tenant, project_id, project_store)
    await _delete_project_reconcile_cron_safe(
        settings=settings,
        tenant=tenant,
        project_id=project.id,
    )
    return await _submit_project_lifecycle(
        operation="delete",
        tenant=tenant,
        project=project,
        reason=body.reason,
        settings=settings,
        source_store=source_store,
        project_store=project_store,
    )


@router.post("/projects/{project_id}/graphrag", status_code=202)
async def submit_project_graphrag(
    project_id: str,
    body: GraphragSubmitRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    project_store: ProjectStore = Depends(_project_store),  # noqa: B008
    source_store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> GraphragSubmitResponse:
    tenant = _require_tenant(principal)
    await _require_project(tenant, project_id, project_store)
    batch_id = body.batch_id.strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required")

    dsn = _path_graph_dsn(settings)
    try:
        plan = await asyncio.to_thread(
            prepare_graphrag_submission,
            tenant,
            project_id,
            batch_id,
            dsn=dsn,
        )
        await asyncio.to_thread(
            assert_project_graphrag_idle,
            source_store,
            tenant,
            project_id,
            batch_id,
        )
    except DownstreamValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DownstreamBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    argo = await submit_graphrag(
        settings=settings,
        tenant=tenant,
        project_id=plan.project_id,
        project_slug=plan.project_slug,
        batch_id=plan.batch_id,
        chunks_key=plan.chunks_key,
    )
    run_id = str(uuid4())
    await asyncio.to_thread(
        source_store.insert_pipeline_run,
        tenant,
        run_id,
        argo["workflow_name"],
        batch_id,
        "submitted",
        argo.get("argo_uid"),
        project_id=project_id,
        run_kind="graphrag",
    )
    return GraphragSubmitResponse(
        batch_id=plan.batch_id,
        chunks_key=plan.chunks_key,
        document_count=plan.document_count,
        workflow_name=argo["workflow_name"],
        workflow_template=settings.PATH_GRAPH_GRAPHRAG_WF_TEMPLATE,
        argo_uid=argo["argo_uid"],
    )


@router.get("/sources", dependencies=[Depends(require_admin)])
async def list_sources(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    project_id: str | None = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> SourcesListResponse:
    tenant = _require_tenant(principal)
    limit = _clamp_page_limit(limit)
    profiles = await asyncio.to_thread(store.list_sources, tenant)
    if project_id:
        profiles = [p for p in profiles if p.project_id == project_id]
    total = len(profiles)
    page = profiles[offset : offset + limit]
    return SourcesListResponse(
        items=[SourceResponse.from_profile(p) for p in page],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/sources", status_code=201)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    project_store: ProjectStore = Depends(_project_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SourceResponse:
    tenant = _require_tenant(principal)
    _validate_schedule_cron(body.schedule_cron)
    project = await asyncio.to_thread(
        project_store.get_project, tenant, body.project_id.strip()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    create = SourceCreate(
        project_id=project.id,
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


@router.get("/sources/{source_id}/workflow-status")
async def source_workflow_status(
    source_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> SourceWorkflowStatusResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    status = await get_source_workflow_status(
        settings=settings,
        store=store,
        tenant=tenant,
        profile=profile,
    )
    return SourceWorkflowStatusResponse(**status)


@router.post("/sources/{source_id}/run", status_code=202)
async def run_source(
    source_id: str,
    request: Request,
    body: RunSourceRequest | None = None,
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

    sync_mode = (body.sync_mode if body is not None else "full").strip().lower()
    if sync_mode not in ("delta", "full"):
        raise HTTPException(status_code=400, detail="sync_mode must be delta or full")

    await assert_source_workflow_idle(
        settings=settings,
        store=store,
        tenant=tenant,
        profile=profile,
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
        sync_mode=sync_mode,
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
        project_id=profile.project_id,
        run_kind="ingest",
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
    except ClientError as exc:
        err = exc.response.get("Error", {})
        code = err.get("Code", "ClientError")
        msg = err.get("Message", str(exc))
        logger.warning(
            "pipeline raw upload S3 failed",
            extra={
                "code": code,
                "bucket": pg_settings.s3_bucket,
                "endpoint": pg_settings.s3_endpoint_url,
            },
        )
        raise HTTPException(
            status_code=502,
            detail=f"S3 upload failed ({code}): {msg}",
        ) from exc

    return UploadFilesResponse(**result)


@router.get("/sources/{source_id}/documents", dependencies=[Depends(require_admin)])
async def list_source_documents(
    source_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    ingest_state: str | None = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> DocumentsListResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")

    limit = _clamp_page_limit(limit)
    dsn = _path_graph_dsn(settings)
    total = await asyncio.to_thread(
        count_documents_for_source,
        tenant,
        profile,
        ingest_state=ingest_state,
        dsn=dsn,
    )
    docs = await asyncio.to_thread(
        list_documents_for_source,
        tenant,
        profile,
        ingest_state=ingest_state,
        limit=limit,
        offset=offset,
        dsn=dsn,
    )
    return DocumentsListResponse(
        items=[DocumentResponse(**d) for d in docs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/documents/{document_id}", dependencies=[Depends(require_admin)])
async def get_document(
    document_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> DocumentDetailResponse:
    tenant = _require_tenant(principal)
    dsn = _path_graph_dsn(settings)
    doc = await asyncio.to_thread(PgMetaStore(dsn).get_document, tenant, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    uri = doc.get("s3_raw_uri") or ""
    filename = filename_from_raw_uri(uri)
    dead_letter_error = None
    if doc.get("ingest_state") == "dead_letter":
        pg_settings = pipeline_blob_settings(settings, dsn)
        dead_letter_error = await asyncio.to_thread(
            _read_dead_letter_error,
            tenant,
            doc["content_hash"],
            pg_settings,
        )
    return DocumentDetailResponse(
        document_id=document_id,
        source_id=doc["source_id"],
        project_id=doc.get("project_id"),
        content_hash=doc["content_hash"],
        ingest_state=doc["ingest_state"],
        s3_raw_uri=uri,
        filename=filename,
        dead_letter_error=dead_letter_error,
    )


@router.post("/documents/{document_id}/purge")
async def purge_document_endpoint(
    document_id: str,
    body: PurgeDocumentRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    return await asyncio.to_thread(
        api_purge_document,
        tenant,
        document_id,
        reason=body.reason,
        hard_raw=body.hard_raw,
    )


@router.post("/documents/{document_id}/restore")
async def restore_document_endpoint(
    document_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    return await asyncio.to_thread(api_restore_document, tenant, document_id)


@router.post("/documents/{document_id}/reingest")
async def reingest_document_endpoint(
    document_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    return await asyncio.to_thread(api_reingest_document, tenant, document_id)


@router.post("/sources/{source_id}/purge")
async def purge_source_endpoint(
    source_id: str,
    body: PurgeReasonRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_source, tenant, source_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return await asyncio.to_thread(
        api_purge_source, tenant, source_id, reason=body.reason
    )


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
    await assert_source_ingest_idle(
        settings=settings,
        store=store,
        tenant=tenant,
        profile=profile,
    )

    document_ids = body.document_ids or None
    dsn = _path_graph_dsn(settings)
    pg_settings = pipeline_blob_settings(settings, dsn)
    try:
        built = await asyncio.to_thread(
            build_ingest_manifest,
            profile,
            document_ids,
            settings=pg_settings,
            dsn=dsn,
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
    settings: Settings = Depends(get_settings),  # noqa: B008
    project_id: str | None = None,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
) -> RunsListResponse:
    tenant = _require_tenant(principal)
    limit = _clamp_page_limit(limit)
    if project_id:
        total = await asyncio.to_thread(
            store.count_pipeline_runs, tenant, project_id=project_id
        )
        runs = await asyncio.to_thread(
            store.list_pipeline_runs,
            tenant,
            limit,
            offset,
            project_id=project_id,
        )
    else:
        total = await asyncio.to_thread(store.count_pipeline_runs, tenant)
        runs = await asyncio.to_thread(store.list_pipeline_runs, tenant, limit, offset)
    runs, argo_available = await enrich_pipeline_runs_with_argo(
        settings=settings,
        runs=runs,
        store=store,
        tenant=tenant,
    )
    return RunsListResponse(
        items=runs,
        total=total,
        limit=limit,
        offset=offset,
        argo_available=argo_available,
    )


@router.get("/dead-letters", dependencies=[Depends(require_admin)])
async def list_dead_letters(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: SourceStore = Depends(_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    project_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    tenant = _require_tenant(principal)
    if project_id:
        items = await asyncio.to_thread(
            list_documents_for_project,
            tenant,
            project_id,
            ingest_state="dead_letter",
            dsn=_path_graph_dsn(settings),
        )
        items = items[:limit]
    else:
        items = await asyncio.to_thread(
            store.list_documents_summary,
            tenant,
            ingest_state="dead_letter",
            limit=limit,
        )
    return {"items": items}
