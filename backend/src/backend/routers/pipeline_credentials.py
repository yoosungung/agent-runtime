from __future__ import annotations

import asyncio
import logging

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend.deps import check_csrf, get_settings, require_admin
from backend.pipeline_credential_secrets import make_credential_secret_store
from backend.pipeline_oauth import (
    exchange_gdrive_code,
    exchange_ms_code,
    gdrive_authorize_url,
    ms_authorize_url,
    secrets_for_driver,
    verify_oauth_state,
)
from backend.settings import Settings
from backend.pipeline_domain import (
    CredentialCreate,
    CredentialProfile,
    CredentialStore,
    OAuthStatus,
    SourceDriver,
)
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline-credentials"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

oauth_router = APIRouter(prefix="/api/pipeline/oauth", tags=["pipeline-oauth"])


class CredentialCreateRequest(BaseModel):
    label: str
    driver: SourceDriver
    config: dict = Field(default_factory=dict)


class CredentialResponse(BaseModel):
    tenant: str
    id: str
    label: str
    driver: SourceDriver
    config: dict
    secret_keys: list[str]
    oauth_status: str
    k8s_secret_name: str
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_profile(cls, profile: CredentialProfile) -> CredentialResponse:
        return cls(
            tenant=profile.tenant,
            id=profile.id,
            label=profile.label,
            driver=profile.driver,
            config=profile.config,
            secret_keys=profile.secret_keys,
            oauth_status=profile.oauth_status.value,
            k8s_secret_name=profile.k8s_secret_name,
            created_at=profile.created_at.isoformat() if profile.created_at else None,
            updated_at=profile.updated_at.isoformat() if profile.updated_at else None,
        )


class OAuthStartResponse(BaseModel):
    authorize_url: str


class CredentialSecretsRequest(BaseModel):
    secrets: dict[str, str]


def _path_graph_dsn(settings: Settings) -> str:
    dsn = settings.PATH_GRAPH_DSN or settings.POSTGRES_DSN
    if not dsn:
        raise HTTPException(status_code=503, detail="PATH_GRAPH_DSN not configured")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _cred_store(settings: Settings = Depends(get_settings)) -> CredentialStore:  # noqa: B008
    return CredentialStore(_path_graph_dsn(settings))


def _require_tenant(principal: Principal) -> str:
    tenant = (principal.tenant or "").strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="User tenant not set")
    return tenant


@router.get("/credentials", dependencies=[Depends(require_admin)])
async def list_credentials(
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
) -> dict:
    tenant = _require_tenant(principal)
    items = await asyncio.to_thread(store.list_credentials, tenant)
    return {"items": [CredentialResponse.from_profile(c) for c in items]}


@router.post("/credentials", status_code=201)
async def create_credential(
    body: CredentialCreateRequest,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
) -> CredentialResponse:
    tenant = _require_tenant(principal)
    create = CredentialCreate(label=body.label, driver=body.driver, config=body.config)
    profile = await asyncio.to_thread(store.create_credential, tenant, create)
    return CredentialResponse.from_profile(profile)


@router.get("/credentials/{credential_id}", dependencies=[Depends(require_admin)])
async def get_credential(
    credential_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
) -> CredentialResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_credential, tenant, credential_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return CredentialResponse.from_profile(profile)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: str,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_credential, tenant, credential_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    secret_store = await make_credential_secret_store(settings, request)
    await secret_store.delete_secret(profile.k8s_secret_name)
    deleted = await asyncio.to_thread(store.delete_credential, tenant, credential_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")


@router.get("/credentials/{credential_id}/oauth/start", dependencies=[Depends(require_admin)])
async def oauth_start(
    credential_id: str,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> OAuthStartResponse:
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_credential, tenant, credential_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    try:
        if profile.driver == SourceDriver.GDRIVE:
            url = gdrive_authorize_url(settings, tenant=tenant, credential_id=credential_id)
        elif profile.driver in (SourceDriver.SHAREPOINT, SourceDriver.ONEDRIVE):
            url = ms_authorize_url(settings, tenant=tenant, credential_id=credential_id)
        else:
            raise HTTPException(status_code=400, detail=f"OAuth not supported for {profile.driver}")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return OAuthStartResponse(authorize_url=url)


@router.put("/credentials/{credential_id}/secrets")
async def put_credential_secrets(
    credential_id: str,
    body: CredentialSecretsRequest,
    request: Request,
    principal: Principal = Depends(require_admin),  # noqa: B008
    store: CredentialStore = Depends(_cred_store),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CredentialResponse:
    """Break-glass / dev: write refresh token without browser OAuth."""
    tenant = _require_tenant(principal)
    profile = await asyncio.to_thread(store.get_credential, tenant, credential_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    secret_store = await make_credential_secret_store(settings, request)
    await secret_store.write(profile.k8s_secret_name, body.secrets)
    updated = await asyncio.to_thread(
        store.mark_connected,
        tenant,
        credential_id,
        secret_keys=list(body.secrets.keys()),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return CredentialResponse.from_profile(updated)


@oauth_router.get("/callback/gdrive")
async def oauth_callback_gdrive(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    settings: Settings = Depends(get_settings),  # noqa: B008
):
    if error:
        return RedirectResponse(url=f"/pipeline/credentials?oauth_error={error}", status_code=302)
    try:
        payload = verify_oauth_state(state, settings)
        tenant = payload["tenant"]
        credential_id = payload["credential_id"]
        tokens = await exchange_gdrive_code(settings, code)
        store = CredentialStore(_path_graph_dsn(settings))
        profile = store.get_credential(tenant, credential_id)
        if profile is None:
            raise ValueError("credential not found")
        secret_store = await make_credential_secret_store(settings, request)
        await secret_store.write(profile.k8s_secret_name, tokens)
        store.mark_connected(tenant, credential_id, secret_keys=list(tokens.keys()))
    except Exception as exc:
        logger.warning("gdrive oauth callback failed: %s", exc)
        return RedirectResponse(
            url=f"/pipeline/credentials?oauth_error={str(exc)[:120]}",
            status_code=302,
        )
    return RedirectResponse(url="/pipeline/credentials?oauth=connected", status_code=302)


@oauth_router.get("/callback/microsoft")
async def oauth_callback_microsoft(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    settings: Settings = Depends(get_settings),  # noqa: B008
):
    if error:
        return RedirectResponse(url=f"/pipeline/credentials?oauth_error={error}", status_code=302)
    try:
        payload = verify_oauth_state(state, settings)
        tenant = payload["tenant"]
        credential_id = payload["credential_id"]
        driver = SourceDriver(payload.get("driver", "sharepoint"))
        tokens = await exchange_ms_code(settings, code)
        secrets = secrets_for_driver(driver, tokens)
        store = CredentialStore(_path_graph_dsn(settings))
        profile = store.get_credential(tenant, credential_id)
        if profile is None:
            raise ValueError("credential not found")
        secret_store = await make_credential_secret_store(settings, request)
        await secret_store.write(profile.k8s_secret_name, secrets)
        store.mark_connected(tenant, credential_id, secret_keys=list(secrets.keys()))
    except Exception as exc:
        logger.warning("microsoft oauth callback failed: %s", exc)
        return RedirectResponse(
            url=f"/pipeline/credentials?oauth_error={str(exc)[:120]}",
            status_code=302,
        )
    return RedirectResponse(url="/pipeline/credentials?oauth=connected", status_code=302)
