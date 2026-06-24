from __future__ import annotations

from fastapi import HTTPException, Request

from backend.pipeline_credential_secrets import make_credential_secret_store
from backend.settings import Settings
from path_graph.admin.credential_settings import merge_credential_into_settings
from path_graph.admin.credentials import CredentialStore
from path_graph.admin.runner import resolve_source_settings
from path_graph.config import Settings as PgSettings, get_settings as get_pg_settings
from path_graph.contracts.source import SourceProfile


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


def _pg_base_settings(dsn: str) -> PgSettings:
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
    base = _pg_base_settings(dsn)
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
