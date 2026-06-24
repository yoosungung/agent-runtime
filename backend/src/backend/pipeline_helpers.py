from __future__ import annotations

import asyncio
import os

from fastapi import HTTPException, Request

from backend.pipeline_argo import _ACTIVE_WORKFLOW_PHASES, get_workflow_phase
from backend.pipeline_credential_secrets import make_credential_secret_store
from backend.settings import Settings
from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.admin.credentials import CredentialStore
from path_graph.admin.runner import resolve_source_settings
from path_graph.admin.sources import SourceStore
from path_graph.config import Settings as PgSettings, get_settings as get_pg_settings
from path_graph.contracts.source import SourceProfile

_INGEST_IN_PROGRESS_MSG = "이 source의 ingest가 이미 수행 중입니다."


async def assert_source_ingest_idle(
    *,
    settings: Settings,
    store: SourceStore,
    tenant: str,
    profile: SourceProfile,
) -> None:
    """Reject a new ingest when the source's latest workflow is still active."""
    if not profile.last_batch_id:
        return

    run = await asyncio.to_thread(
        store.get_pipeline_run_by_batch, tenant, profile.last_batch_id
    )
    workflow_name = (run or {}).get("workflow_name") or ""
    if workflow_name:
        phase = await get_workflow_phase(settings=settings, workflow_name=workflow_name)
        if phase and phase in _ACTIVE_WORKFLOW_PHASES:
            raise HTTPException(status_code=409, detail=_INGEST_IN_PROGRESS_MSG)
        return

    if profile.last_run_status == "submitted":
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
