from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from fastapi import HTTPException, Request

from backend.pipeline_argo import (
    _ACTIVE_WORKFLOW_PHASES,
    _TERMINAL_WORKFLOW_PHASES,
    get_workflow_phase,
    get_workflow_status,
)
from backend.pipeline_credential_secrets import make_credential_secret_store
from backend.settings import Settings
from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.admin.credentials import CredentialStore
from path_graph.admin.runner import resolve_source_settings
from path_graph.admin.sources import SourceStore
from path_graph.config import Settings as PgSettings, get_settings as get_pg_settings
from path_graph.contracts.source import SourceProfile

_INGEST_IN_PROGRESS_MSG = "이 source의 ingest가 이미 수행 중입니다."
_WORKFLOW_IN_PROGRESS_MSG = "이 source의 workflow가 이미 수행 중입니다."

logger = logging.getLogger(__name__)


def _active_from_db_status(profile: SourceProfile) -> bool:
    return profile.last_run_status == "submitted"


_BATCH_ID_TS_RE = re.compile(r"^(\d{8})-(\d{6})$")


def started_at_from_batch_id(batch_id: str | None) -> str | None:
    """Parse UTC batch id ``YYYYMMDD-HHMMSS`` into an ISO timestamp."""
    if not batch_id:
        return None
    match = _BATCH_ID_TS_RE.fullmatch(batch_id.strip())
    if not match:
        return None
    day, clock = match.group(1), match.group(2)
    return f"{day[:4]}-{day[4:6]}-{day[6:8]}T{clock[:2]}:{clock[2:4]}:{clock[4:6]}Z"


def _apply_batch_started_fallback(run: dict[str, Any]) -> dict[str, Any]:
    if run.get("started_at"):
        return run
    parsed = started_at_from_batch_id(str(run.get("batch_id") or ""))
    if parsed:
        run["started_at"] = parsed
    return run


async def get_source_workflow_status(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    profile: SourceProfile,
) -> dict[str, Any]:
    """Return whether the source's latest workflow is still active in Argo."""
    result: dict[str, Any] = {
        "active": False,
        "workflow_name": None,
        "phase": None,
        "batch_id": profile.last_batch_id,
        "last_run_status": profile.last_run_status,
        "argo_available": True,
    }
    if not profile.last_batch_id:
        if _active_from_db_status(profile):
            result["active"] = True
        return result

    run = await asyncio.to_thread(
        store.get_pipeline_run_by_batch, tenant, profile.last_batch_id
    )
    workflow_name = (run or {}).get("workflow_name") or ""
    if workflow_name:
        result["workflow_name"] = workflow_name
        try:
            phase = await get_workflow_phase(settings=settings, workflow_name=workflow_name)
        except HTTPException as exc:
            logger.warning(
                "argo phase lookup failed for %s: %s",
                workflow_name,
                exc.detail,
            )
            result["argo_available"] = False
            if _active_from_db_status(profile):
                result["active"] = True
            return result
        result["phase"] = phase
        if phase and phase in _ACTIVE_WORKFLOW_PHASES:
            result["active"] = True
        return result

    if _active_from_db_status(profile):
        result["active"] = True
    return result


def _is_terminal_pipeline_run(run: dict[str, Any]) -> bool:
    return str(run.get("status") or "").strip() in _TERMINAL_WORKFLOW_PHASES


def _merge_persisted_run_fields(enriched: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    for key in ("status", "started_at", "ended_at"):
        if run.get(key) is not None:
            enriched[key] = run[key]
    return enriched


async def _persist_terminal_run(
    *,
    store: SourceStore,
    tenant: str,
    run: dict[str, Any],
    wf_status: dict[str, str | None],
) -> None:
    phase = str(wf_status.get("phase") or "").strip()
    if phase not in _TERMINAL_WORKFLOW_PHASES:
        return
    await asyncio.to_thread(
        store.finalize_pipeline_run,
        tenant,
        str(run["id"]),
        phase,
        wf_status.get("started_at"),
        wf_status.get("ended_at"),
    )


async def enrich_pipeline_runs_with_argo(
    *,
    settings: Settings,
    runs: list[dict[str, Any]],
    store: SourceStore | None = None,
    tenant: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Merge Argo Workflow phase/timestamps into PG pipeline run rows."""
    if not runs:
        return runs, True

    argo_available = True

    async def enrich_one(run: dict[str, Any]) -> dict[str, Any]:
        nonlocal argo_available
        enriched = {
            **run,
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
        }
        if _is_terminal_pipeline_run(run):
            return _apply_batch_started_fallback(enriched)

        workflow_name = str(run.get("workflow_name") or "").strip()
        if not workflow_name:
            return _apply_batch_started_fallback(enriched)
        try:
            wf_status = await get_workflow_status(
                settings=settings,
                workflow_name=workflow_name,
            )
        except HTTPException:
            argo_available = False
            return _apply_batch_started_fallback(_merge_persisted_run_fields(enriched, run))
        if wf_status is None:
            if _is_terminal_pipeline_run(run):
                return _apply_batch_started_fallback(enriched)
            return _apply_batch_started_fallback(_merge_persisted_run_fields(enriched, run))
        enriched["status"] = wf_status["phase"] or run.get("status")
        enriched["started_at"] = wf_status["started_at"]
        enriched["ended_at"] = wf_status["ended_at"]
        if store is not None and tenant is not None:
            await _persist_terminal_run(
                store=store,
                tenant=tenant,
                run=run,
                wf_status=wf_status,
            )
        return _apply_batch_started_fallback(enriched)

    enriched_runs = await asyncio.gather(*(enrich_one(run) for run in runs))
    return list(enriched_runs), argo_available


async def assert_source_workflow_idle(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    profile: SourceProfile,
) -> None:
    """Reject a new workflow when the source's latest run is still active."""
    status = await get_source_workflow_status(
        settings=settings,
        store=store,
        tenant=tenant,
        profile=profile,
    )
    if status["active"]:
        raise HTTPException(status_code=409, detail=_WORKFLOW_IN_PROGRESS_MSG)


async def assert_source_ingest_idle(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    profile: SourceProfile,
) -> None:
    """Reject a new ingest when the source's latest workflow is still active."""
    status = await get_source_workflow_status(
        settings=settings,
        store=store,
        tenant=tenant,
        profile=profile,
    )
    if status["active"]:
        raise HTTPException(status_code=409, detail=_INGEST_IN_PROGRESS_MSG)


async def resolve_credential_secret(
    request,
    settings: Settings,
    profile: SourceProfile,
    dsn: str,
    *,
    require_connected: bool = False,
) -> str:
    if not profile.credential_id:
        return ""
    cred_store = CredentialStore(dsn)
    credential = cred_store.get_credential(profile.tenant, profile.credential_id)
    if credential is None:
        raise HTTPException(status_code=400, detail="Source credential not found")
    if require_connected and credential.oauth_status != "connected":
        raise HTTPException(
            status_code=400,
            detail="Credential is not connected — complete OAuth first",
        )
    if require_connected or profile.enabled:
        secret_store = await make_credential_secret_store(settings, request)
        secret_values = await secret_store.read(credential.k8s_secret_name)
        if require_connected and not secret_values:
            raise HTTPException(
                status_code=400,
                detail="Credential is not connected — complete OAuth or set secrets",
            )
    return credential.k8s_secret_name


def _infer_s3_region(endpoint: str, region: str) -> str:
    """Default Garage region when S3_REGION is unset (common in local port-forward)."""
    normalized = region.strip() or "us-east-1"
    if normalized != "us-east-1":
        return normalized
    lowered = endpoint.lower()
    if "garage" in lowered or ":3900" in lowered:
        return "garage"
    return normalized


def pipeline_blob_settings(backend: Settings, dsn: str) -> PgSettings:
    """Align path-graph blob store with pipeline Argo pods (Garage S3).

    agents-runtime backend defaults path-graph to local storage unless env is set.
    Map runtime s3-creds (S3_ACCESS_KEY_ID) → path-graph S3_ACCESS_KEY fields.
    """
    base = get_pg_settings()
    normalized = dsn.replace("postgresql+asyncpg://", "postgresql://")
    updates: dict[str, object] = {}
    if base.path_graph_dsn != normalized:
        updates["path_graph_dsn"] = normalized

    endpoint = (
        os.environ.get("S3_ENDPOINT_URL", "").strip()
        or backend.S3_ENDPOINT_URL
        or base.s3_endpoint_url
    ).strip()
    bucket = (
        os.environ.get("PATH_GRAPH_S3_BUCKET", "").strip()
        or os.environ.get("S3_BUCKET", "").strip()
        or backend.S3_BUCKET
        or base.s3_bucket
    ).strip()
    access = (
        os.environ.get("S3_ACCESS_KEY", "").strip()
        or os.environ.get("S3_ACCESS_KEY_ID", "").strip()
        or backend.S3_ACCESS_KEY_ID
        or base.s3_access_key
    ).strip()
    secret = (
        os.environ.get("S3_SECRET_KEY", "").strip()
        or os.environ.get("S3_SECRET_ACCESS_KEY", "").strip()
        or backend.S3_SECRET_ACCESS_KEY
        or base.s3_secret_key
    ).strip()
    region = _infer_s3_region(
        endpoint,
        (
            os.environ.get("S3_REGION", "").strip()
            or backend.S3_REGION
            or base.s3_region
            or "us-east-1"
        ).strip(),
    )

    want_s3 = (
        os.environ.get("PIPELINE_STORAGE_BACKEND", "").strip().lower() == "s3"
        or base.pipeline_storage_backend.strip().lower() == "s3"
    )
    if (want_s3 or (endpoint and bucket and access and secret)) and (
        endpoint and bucket and access and secret
    ):
        updates.update(
            {
                "pipeline_storage_backend": "s3",
                "s3_endpoint_url": endpoint,
                "s3_bucket": bucket,
                "s3_access_key": access,
                "s3_secret_key": secret,
                "s3_region": region,
            }
        )

    return base.model_copy(update=updates) if updates else base


def _pg_base_settings(dsn: str, backend: Settings | None = None) -> PgSettings:
    if backend is not None:
        return pipeline_blob_settings(backend, dsn)
    base = get_pg_settings()
    normalized = dsn.replace("postgresql+asyncpg://", "postgresql://")
    if base.path_graph_dsn == normalized:
        return base
    return base.model_copy(update={"path_graph_dsn": normalized})


async def pg_settings_for_source(
    request: Request,
    settings: Settings,
    profile: SourceProfile,
    dsn: str,
) -> PgSettings:
    base = _pg_base_settings(dsn, settings)
    if not profile.credential_id:
        return base

    cred_store = CredentialStore(dsn)
    credential = cred_store.get_credential(profile.tenant, profile.credential_id)
    if credential is None:
        raise HTTPException(status_code=400, detail="Source credential not found")
    if credential.driver != profile.driver:
        raise HTTPException(status_code=400, detail="Credential driver does not match source driver")

    secret_store = await make_credential_secret_store(settings, request)
    secret_values = await secret_store.read(credential.k8s_secret_name)
    if not secret_values:
        raise HTTPException(
            status_code=400,
            detail="Credential is not connected — complete OAuth or set secrets",
        )

    return resolve_source_settings(
        profile,
        dsn=dsn,
        secret_values=secret_values,
        platform_client_id=_platform_client_id(settings, profile.driver),
        platform_client_secret=_platform_client_secret(settings, profile.driver),
        platform_ms_tenant_id=settings.PIPELINE_MS_TENANT_ID,
        settings=base,
    )


def _platform_client_id(settings: Settings, driver) -> str:
    from path_graph.contracts.source import SourceDriver

    if driver == SourceDriver.GDRIVE:
        return settings.PIPELINE_GDRIVE_CLIENT_ID
    return settings.PIPELINE_MS_CLIENT_ID


def _platform_client_secret(settings: Settings, driver) -> str:
    from path_graph.contracts.source import SourceDriver

    if driver == SourceDriver.GDRIVE:
        return settings.PIPELINE_GDRIVE_CLIENT_SECRET
    return settings.PIPELINE_MS_CLIENT_SECRET
