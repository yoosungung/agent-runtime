from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import audit_patch_details, log_event, make_audit_row
from backend.bundle_storage import BundleStorage, bundle_path
from backend.knowledge_validation import validate_knowledge_projects
from backend.deps import (
    check_csrf,
    get_db,
    get_principal,
    get_settings,
    require_admin,
    require_developer,
)
from backend.settings import Settings
from runtime_common.config_schema import (
    GeneralAgentSourceConfig,
    HermesGeneralSourceConfig,
    KnowledgePolicyConfig,
    McpToolManifestEntry,
    SourceConfig,
    UserMetaFormTemplate,
)
from runtime_common.db.models import SourceMetaRow, UserResourceAccessRow, UserRow
from runtime_common.general_visibility import (
    GeneralVisibility,
    can_manage_general_agent,
    can_use_general_agent,
    validate_tenant_visibility,
)
from runtime_common.roles import UserRole, role_at_least
from runtime_common.schemas import AgentRuntimeKind, McpRuntimeKind, Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/source-meta",
    tags=["source-meta"],
    dependencies=[Depends(get_principal), Depends(check_csrf)],
)

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _ensure_can_read_source_meta(row: SourceMetaRow, principal: Principal) -> None:
    if row.deploy_mode in ("general", "hermes_general"):
        if not can_use_general_agent(
            visibility=row.visibility,
            created_by_user_id=row.created_by_user_id,
            owner_tenant=row.owner_tenant,
            principal_user_id=principal.user_id,
            principal_tenant=principal.tenant,
            is_admin=principal.is_admin,
        ) and not role_at_least(principal.role, UserRole.DEVELOPER):
            raise HTTPException(status_code=403, detail="Access denied")
        return
    if not role_at_least(principal.role, UserRole.DEVELOPER):
        raise HTTPException(status_code=403, detail="Developer access required")


def _ensure_can_write_source_meta(row: SourceMetaRow, principal: Principal) -> None:
    if row.deploy_mode in ("general", "hermes_general"):
        if not can_manage_general_agent(
            created_by_user_id=row.created_by_user_id,
            principal_user_id=principal.user_id,
            is_admin=principal.is_admin,
        ):
            raise HTTPException(status_code=403, detail="Only the creator or admin can modify this agent")
        return
    _ensure_can_read_source_meta(row, principal)


def _general_visibility_filter(principal: Principal):
    return or_(
        SourceMetaRow.created_by_user_id == principal.user_id,
        SourceMetaRow.visibility == GeneralVisibility.PUBLIC,
        and_(
            SourceMetaRow.visibility == GeneralVisibility.TENANT,
            SourceMetaRow.owner_tenant.isnot(None),
            SourceMetaRow.owner_tenant == principal.tenant,
        ),
    )


def _apply_role_list_filter(
    principal: Principal,
    q,
    count_q,
):
    if role_at_least(principal.role, UserRole.DEVELOPER):
        return q, count_q
    q = q.where(SourceMetaRow.deploy_mode.in_(("general", "hermes_general")))
    count_q = count_q.where(SourceMetaRow.deploy_mode.in_(("general", "hermes_general")))
    visibility_filter = _general_visibility_filter(principal)
    q = q.where(visibility_filter)
    count_q = count_q.where(visibility_filter)
    return q, count_q


GENERAL_RUNTIME_POOL = "agent:compiled_graph"
HERMES_RUNTIME_POOL = "agent:hermes"
MAX_MCP_TOOLS = 32


async def _discover_mcp_tools(
    settings: Settings,
    access_token: str,
    mcp_servers: list[str],
) -> list[McpToolManifestEntry]:
    """Fetch tool manifests from ext-authz via Envoy for each MCP server."""
    tools: list[McpToolManifestEntry] = []
    base = settings.ENVOY_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for server in mcp_servers:
            try:
                resp = await client.get(
                    f"{base}/v1/mcp/servers/{server}/catalog",
                    headers=headers,
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"MCP tool discovery failed for server '{server}': {exc}",
                ) from exc
            payload = resp.json()
            for raw in payload.get("tools") or []:
                if not isinstance(raw, dict) or not raw.get("name"):
                    continue
                tools.append(
                    McpToolManifestEntry(
                        server=server,
                        name=str(raw["name"]),
                        description=str(raw.get("description") or ""),
                    )
                )
                if len(tools) >= MAX_MCP_TOOLS:
                    return tools
    return tools


def _build_general_config(
    system_prompt: str,
    mcp_servers: list[str],
    mcp_tools: list[McpToolManifestEntry],
    extra_config: dict | None,
    *,
    knowledge_project_ids: list[str] | None = None,
    mcp_requires_knowledge: list[str] | None = None,
    delegate_agents: list[str] | None = None,
    allow_agent_delegation: bool = True,
) -> dict:
    general = GeneralAgentSourceConfig(
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
        mcp_tools=mcp_tools,
        knowledge_project_ids=knowledge_project_ids or [],
        mcp_requires_knowledge=mcp_requires_knowledge or [],
        delegate_agents=delegate_agents or [],
        allow_agent_delegation=allow_agent_delegation,
    )
    config = dict(extra_config or {})
    config["general"] = general.model_dump()
    return config


def _pipeline_project_store(settings: Settings):
    from backend.routers.pipeline import _path_graph_dsn
    from backend.pipeline_domain import ProjectStore

    return ProjectStore(_path_graph_dsn(settings))


def _build_hermes_config(
    soul: str,
    mcp_servers: list[str],
    mcp_tools: list[McpToolManifestEntry],
    *,
    skills: list[str],
    model: str,
    extra_config: dict | None,
) -> dict:
    hermes = HermesGeneralSourceConfig(
        soul=soul.strip(),
        mcp_servers=mcp_servers,
        mcp_tools=mcp_tools,
        skills=skills,
        model=model,
    )
    config = dict(extra_config or {})
    config["hermes"] = hermes.model_dump()
    return config


VALID_KINDS = {"agent", "mcp"}
VALID_DEPLOY_MODES = {"bundle", "general", "image", "hermes_general"}
VALID_BUNDLE_RUNTIME_POOLS = {
    f"agent:{k}" for k in AgentRuntimeKind if k != AgentRuntimeKind.CUSTOM
} | {f"mcp:{k}" for k in McpRuntimeKind if k != McpRuntimeKind.CUSTOM}

RE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
RE_VERSION = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
RE_ENTRYPOINT = re.compile(r"^[\w.]+:[\w]+$")
RE_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
RE_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
RE_SECRETS_REF = re.compile(r"^(vault|env|aws-sm)://.+$")
RE_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
RE_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# Merged config (source + user) must fit in Envoy header budget.
# base64(16KB JSON) ≈ 21.8KB + other headers → safely within 64KB max_request_headers_kb.
MAX_MERGED_CONFIG_BYTES = 16 * 1024  # 16KB


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {VALID_KINDS}")


def _validate_deploy_mode(deploy_mode: str) -> None:
    if deploy_mode not in VALID_DEPLOY_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"deploy_mode must be one of {sorted(VALID_DEPLOY_MODES)}",
        )


def _validate_runtime_pool(runtime_pool: str, kind: str) -> None:
    if runtime_pool not in VALID_BUNDLE_RUNTIME_POOLS:
        raise HTTPException(
            status_code=400,
            detail=f"runtime_pool must be one of {sorted(VALID_BUNDLE_RUNTIME_POOLS)}",
        )
    if not runtime_pool.startswith(f"{kind}:"):
        raise HTTPException(
            status_code=400,
            detail=f"runtime_pool prefix must match kind '{kind}'",
        )


def _validate_slug(slug: str) -> None:
    if not RE_SLUG.match(slug) or len(slug) > 45:
        raise HTTPException(
            status_code=400,
            detail="slug must match [a-z0-9]([a-z0-9-]*[a-z0-9])? and be ≤ 45 chars",
        )


def _validate_image_digest(digest: str | None) -> None:
    if digest is not None and not RE_IMAGE_DIGEST.match(digest):
        raise HTTPException(
            status_code=400,
            detail="image_digest must match ^sha256:[0-9a-f]{64}$",
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
    if len(serialized.encode()) > MAX_MERGED_CONFIG_BYTES:
        raise HTTPException(
            status_code=413,
            detail="config exceeds 16KB limit (merged source+user config must fit in Envoy headers)",
        )
    knowledge = config.get("knowledge")
    if knowledge is not None:
        try:
            KnowledgePolicyConfig.model_validate(knowledge)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Pydantic response schemas
# ---------------------------------------------------------------------------


def _validate_delegate_agents(principal: Principal, delegate_agents: list[str]) -> None:
    for agent_name in delegate_agents:
        if not principal.can_access("agent", agent_name):
            raise HTTPException(
                status_code=403,
                detail=f"No access to delegate agent '{agent_name}'",
            )


def _validate_general_visibility(visibility: str, owner_tenant: str | None) -> None:
    if visibility not in {v.value for v in GeneralVisibility}:
        raise HTTPException(
            status_code=400,
            detail=f"visibility must be one of {[v.value for v in GeneralVisibility]}",
        )
    try:
        validate_tenant_visibility(visibility, owner_tenant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _resolve_creator_tenant(
    db: AsyncSession,
    principal: Principal,
    *,
    fallback: str | None = None,
) -> str | None:
    """JWT tenant claim can be stale; prefer DB for visibility checks."""
    if principal.tenant:
        return principal.tenant
    result = await db.execute(select(UserRow.tenant).where(UserRow.id == principal.user_id))
    tenant = result.scalar_one_or_none()
    return tenant if tenant else fallback


class SourceMetaResponse(BaseModel):
    id: int
    kind: str
    name: str
    version: str
    runtime_pool: str
    entrypoint: str | None
    bundle_uri: str | None
    checksum: str | None
    sig_uri: str | None
    config: dict
    user_meta_template: dict
    retired: bool
    deploy_mode: str
    image_uri: str | None
    image_digest: str | None
    slug: str | None
    status: str
    created_by_user_id: int | None = None
    owner_tenant: str | None = None
    visibility: str = GeneralVisibility.PRIVATE
    chat_selectable: bool = True
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
    deploy_mode: str | None = Query(None),
    name: str | None = Query(None, description="Name prefix filter"),
    retired: bool | None = Query(None),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SourceMetaListResponse:
    limit = min(limit, 100)
    if deploy_mode is not None:
        _validate_deploy_mode(deploy_mode)
        if deploy_mode not in ("general", "hermes_general") and not role_at_least(
            principal.role, UserRole.DEVELOPER
        ):
            raise HTTPException(status_code=403, detail="Developer access required")
    q = select(SourceMetaRow)
    count_q = select(func.count()).select_from(SourceMetaRow)
    q, count_q = _apply_role_list_filter(principal, q, count_q)

    if kind is not None:
        q = q.where(SourceMetaRow.kind == kind)
        count_q = count_q.where(SourceMetaRow.kind == kind)
    if deploy_mode is not None:
        q = q.where(SourceMetaRow.deploy_mode == deploy_mode)
        count_q = count_q.where(SourceMetaRow.deploy_mode == deploy_mode)
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
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    _ensure_can_read_source_meta(row, principal)
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
    principal=Depends(require_developer),
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
    chat_selectable = bool(meta_dict.get("chat_selectable", True))

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
        chat_selectable=chat_selectable if kind == "agent" else True,
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
# POST /api/source-meta/general  (config-only agent — no bundle)
# ---------------------------------------------------------------------------


class GeneralAgentCreateRequest(BaseModel):
    name: str
    version: str
    system_prompt: str
    mcp_servers: list[str]
    knowledge_project_ids: list[str] = []
    delegate_agents: list[str] = []
    config: dict = {}
    visibility: str = GeneralVisibility.PRIVATE
    chat_selectable: bool = True


@router.post("/general", response_model=SourceMetaResponse, status_code=201)
async def create_general_agent(
    request: Request,
    body: GeneralAgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    _validate_name(body.name)
    _validate_version(body.version)
    if not body.system_prompt.strip():
        raise HTTPException(status_code=400, detail="system_prompt is required")
    if not body.mcp_servers:
        raise HTTPException(status_code=400, detail="mcp_servers must not be empty")

    for server in body.mcp_servers:
        if not principal.can_access("mcp", server):
            raise HTTPException(
                status_code=403,
                detail=f"No access to MCP server '{server}'",
            )

    _validate_delegate_agents(principal, body.delegate_agents)

    owner_tenant = await _resolve_creator_tenant(db, principal)
    _validate_general_visibility(body.visibility, owner_tenant)

    project_store = _pipeline_project_store(settings)
    mcp_requires_knowledge = await validate_knowledge_projects(
        db,
        tenant=owner_tenant,
        project_ids=body.knowledge_project_ids,
        mcp_servers=body.mcp_servers,
        project_store=project_store,
    )

    access_token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE)
    if not access_token:
        raise HTTPException(status_code=401, detail="access token required for MCP discovery")

    mcp_tools = await _discover_mcp_tools(settings, access_token, body.mcp_servers)
    extra = dict(body.config)
    extra.pop("general", None)
    config = _build_general_config(
        body.system_prompt.strip(),
        body.mcp_servers,
        mcp_tools,
        extra,
        knowledge_project_ids=body.knowledge_project_ids,
        mcp_requires_knowledge=mcp_requires_knowledge,
        delegate_agents=body.delegate_agents,
    )
    _validate_config(config)

    row = SourceMetaRow(
        kind="agent",
        name=body.name,
        version=body.version,
        runtime_pool=GENERAL_RUNTIME_POOL,
        entrypoint=None,
        bundle_uri=None,
        checksum=None,
        sig_uri=None,
        config=config,
        retired=False,
        deploy_mode="general",
        image_uri=None,
        image_digest=None,
        slug=None,
        status="active",
        created_by_user_id=principal.user_id,
        owner_tenant=owner_tenant,
        visibility=body.visibility,
        chat_selectable=body.chat_selectable,
    )
    db.add(row)
    db.add(
        make_audit_row(
            "source_meta.create_general",
            principal.user_id,
            principal.sub,
            kind="agent",
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
            detail=f"source_meta (kind=agent, name={body.name}, version={body.version}) already exists",
        ) from exc

    log_event(
        "source_meta.create_general",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=row.id,
        name=body.name,
        version=body.version,
        mcp_tool_count=len(mcp_tools),
    )
    return _row_to_response(row)


class GeneralAgentPatchRequest(BaseModel):
    system_prompt: str | None = None
    mcp_servers: list[str] | None = None
    knowledge_project_ids: list[str] | None = None
    delegate_agents: list[str] | None = None
    config: dict | None = None
    visibility: str | None = None
    chat_selectable: bool | None = None


@router.patch("/general/{id}", response_model=SourceMetaResponse)
async def patch_general_agent(
    id: int,
    request: Request,
    body: GeneralAgentPatchRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    if row.deploy_mode != "general" or row.kind != "agent":
        raise HTTPException(status_code=400, detail="Not a general agent")
    _ensure_can_write_source_meta(row, principal)

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if body.visibility is not None:
        owner_tenant = await _resolve_creator_tenant(db, principal, fallback=row.owner_tenant)
        _validate_general_visibility(body.visibility, owner_tenant)
        row.visibility = body.visibility
        if body.visibility == GeneralVisibility.TENANT:
            row.owner_tenant = owner_tenant

    if body.chat_selectable is not None:
        row.chat_selectable = body.chat_selectable

    if body.delegate_agents is not None:
        _validate_delegate_agents(principal, body.delegate_agents)

    if body.mcp_servers is not None:
        if not body.mcp_servers:
            raise HTTPException(status_code=400, detail="mcp_servers must not be empty")
        for server in body.mcp_servers:
            if not principal.can_access("mcp", server):
                raise HTTPException(
                    status_code=403,
                    detail=f"No access to MCP server '{server}'",
                )

    needs_config_rebuild = any(
        field in update_data
        for field in (
            "system_prompt",
            "mcp_servers",
            "config",
            "knowledge_project_ids",
            "delegate_agents",
        )
    )
    if needs_config_rebuild or body.knowledge_project_ids is not None:
        general_cfg = row.config.get("general", {})
        system_prompt = (
            body.system_prompt.strip()
            if body.system_prompt is not None
            else general_cfg.get("system_prompt", "")
        )
        if not system_prompt:
            raise HTTPException(status_code=400, detail="system_prompt is required")
        mcp_servers = body.mcp_servers if body.mcp_servers is not None else general_cfg.get(
            "mcp_servers", []
        )
        if not mcp_servers:
            raise HTTPException(status_code=400, detail="mcp_servers must not be empty")
        knowledge_project_ids = (
            body.knowledge_project_ids
            if body.knowledge_project_ids is not None
            else general_cfg.get("knowledge_project_ids", [])
        )
        delegate_agents = (
            body.delegate_agents
            if body.delegate_agents is not None
            else general_cfg.get("delegate_agents", [])
        )

        owner_tenant = await _resolve_creator_tenant(db, principal, fallback=row.owner_tenant)
        project_store = _pipeline_project_store(settings)
        mcp_requires_knowledge = await validate_knowledge_projects(
            db,
            tenant=owner_tenant,
            project_ids=knowledge_project_ids,
            mcp_servers=mcp_servers,
            project_store=project_store,
        )

        access_token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE)
        if not access_token:
            raise HTTPException(status_code=401, detail="access token required for MCP discovery")

        mcp_tools = await _discover_mcp_tools(settings, access_token, mcp_servers)
        extra_config = body.config if body.config is not None else {
            k: v for k, v in row.config.items() if k != "general"
        }
        extra_config.pop("general", None)
        config = _build_general_config(
            system_prompt,
            mcp_servers,
            mcp_tools,
            extra_config,
            knowledge_project_ids=knowledge_project_ids,
            mcp_requires_knowledge=mcp_requires_knowledge,
            delegate_agents=delegate_agents,
        )
        _validate_config(config)
        row.config = config

    db.add(
        make_audit_row(
            "source_meta.patch_general",
            principal.user_id,
            principal.sub,
            source_meta_id=id,
            **audit_patch_details(update_data),
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(row)

    log_event(
        "source_meta.patch_general",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=row.id,
        **audit_patch_details(update_data),
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
    chat_selectable: bool = True


@router.post("", response_model=SourceMetaResponse, status_code=201)
async def create_source_meta(
    request: Request,
    body: SourceMetaCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_developer),
) -> SourceMetaResponse:
    _validate_kind(body.kind)
    _validate_name(body.name)
    _validate_version(body.version)
    _validate_runtime_pool(body.runtime_pool, body.kind)
    _validate_entrypoint(body.entrypoint)
    _validate_checksum(body.checksum)
    _validate_config(body.config)
    try:
        root_cfg = SourceConfig.model_validate(body.config)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _validate_delegate_agents(principal, root_cfg.delegate_agents)

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
        chat_selectable=body.chat_selectable if body.kind == "agent" else True,
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

ALLOWED_PATCH_FIELDS = {"entrypoint", "sig_uri", "runtime_pool", "config", "user_meta_template"}
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
    user_meta_template: dict | None = None
    chat_selectable: bool | None = None


@router.patch("/{id}", response_model=SourceMetaResponse)
async def patch_source_meta(
    id: int,
    body: SourceMetaPatchRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    _ensure_can_write_source_meta(row, principal)

    update_data = body.model_dump(exclude_none=True)

    if body.entrypoint is not None:
        _validate_entrypoint(body.entrypoint)
    if body.runtime_pool is not None:
        _validate_runtime_pool(body.runtime_pool, row.kind)
    if body.config is not None:
        _validate_config(body.config)
    if body.chat_selectable is not None and row.kind != "agent":
        raise HTTPException(
            status_code=400,
            detail="chat_selectable applies to agent resources only",
        )
    if body.user_meta_template is not None:
        try:
            UserMetaFormTemplate.model_validate(body.user_meta_template)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

    for field, value in update_data.items():
        setattr(row, field, value)

    db.add(
        make_audit_row(
            "source_meta.patch",
            principal.user_id,
            principal.sub,
            source_meta_id=id,
            **audit_patch_details(update_data),
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(row)

    log_event(
        "source_meta.patch",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=id,
        **audit_patch_details(update_data),
    )

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/source-meta/{id}/retire
# ---------------------------------------------------------------------------


@router.post("/{id}/retire", response_model=SourceMetaResponse)
async def retire_source_meta(
    id: int,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    _ensure_can_write_source_meta(row, principal)

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
    principal: Principal = Depends(get_principal),
) -> None:
    if not settings.ALLOW_HARD_DELETE:
        raise HTTPException(
            status_code=403, detail="Hard delete not allowed (ALLOW_HARD_DELETE=false)"
        )

    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    _ensure_can_write_source_meta(row, principal)

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
    _principal: Principal = Depends(require_admin),
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


# ---------------------------------------------------------------------------
# POST /api/source-meta/hermes-general  (Hermes profile agent — no bundle)
# ---------------------------------------------------------------------------


class HermesAgentCreateRequest(BaseModel):
    name: str
    version: str
    soul: str
    mcp_servers: list[str]
    skills: list[str] = []
    model: str = ""
    config: dict = {}
    visibility: str = GeneralVisibility.PRIVATE


@router.post("/hermes-general", response_model=SourceMetaResponse, status_code=201)
async def create_hermes_general_agent(
    request: Request,
    body: HermesAgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    from hermes_base.vfs_profile import ProfileVfsSync

    _validate_name(body.name)
    _validate_version(body.version)
    if not body.soul.strip():
        raise HTTPException(status_code=400, detail="soul is required")
    if not body.mcp_servers:
        raise HTTPException(status_code=400, detail="mcp_servers must not be empty")

    for server in body.mcp_servers:
        if not principal.can_access("mcp", server):
            raise HTTPException(
                status_code=403,
                detail=f"No access to MCP server '{server}'",
            )

    owner_tenant = await _resolve_creator_tenant(db, principal)
    _validate_general_visibility(body.visibility, owner_tenant)

    access_token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE)
    if not access_token:
        raise HTTPException(status_code=401, detail="access token required for MCP discovery")

    mcp_tools = await _discover_mcp_tools(settings, access_token, body.mcp_servers)
    config = _build_hermes_config(
        body.soul,
        body.mcp_servers,
        mcp_tools,
        skills=body.skills,
        model=body.model,
        extra_config=body.config,
    )
    _validate_config(config)

    row = SourceMetaRow(
        kind="agent",
        name=body.name,
        version=body.version,
        runtime_pool=HERMES_RUNTIME_POOL,
        entrypoint=None,
        bundle_uri=None,
        checksum=None,
        sig_uri=None,
        config=config,
        retired=False,
        deploy_mode="hermes_general",
        image_uri=None,
        image_digest=None,
        slug=None,
        status="active",
        created_by_user_id=principal.user_id,
        owner_tenant=owner_tenant,
        visibility=body.visibility,
    )
    db.add(row)
    db.add(
        make_audit_row(
            "source_meta.create_hermes_general",
            principal.user_id,
            principal.sub,
            kind="agent",
            name=body.name,
            version=body.version,
        )
    )
    try:
        await db.flush()
        vfs_store = getattr(request.app.state, "vfs_agent_store", None)
        if vfs_store is None:
            raise HTTPException(status_code=503, detail="VFS store not configured (set VFS_DSN)")
        vfs_sync = ProfileVfsSync(vfs_store)
        session_dsn = (settings.VFS_DSN or settings.POSTGRES_DSN or "").replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        await vfs_sync.seed_from_config(
            body.name,
            config,
            session_dsn=session_dsn or None,
        )
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"source_meta (kind=agent, name={body.name}, version={body.version}) already exists",
        ) from exc

    log_event(
        "source_meta.create_hermes_general",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=row.id,
        name=body.name,
        version=body.version,
        mcp_tool_count=len(mcp_tools),
    )
    return _row_to_response(row)


class HermesAgentPatchRequest(BaseModel):
    soul: str | None = None
    mcp_servers: list[str] | None = None
    skills: list[str] | None = None
    model: str | None = None
    config: dict | None = None
    visibility: str | None = None


@router.patch("/hermes-general/{id}", response_model=SourceMetaResponse)
async def patch_hermes_general_agent(
    id: int,
    request: Request,
    body: HermesAgentPatchRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SourceMetaResponse:
    result = await db.execute(select(SourceMetaRow).where(SourceMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    if row.deploy_mode != "hermes_general" or row.kind != "agent":
        raise HTTPException(status_code=400, detail="Not a hermes general agent")
    _ensure_can_write_source_meta(row, principal)

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if body.visibility is not None:
        owner_tenant = await _resolve_creator_tenant(db, principal, fallback=row.owner_tenant)
        _validate_general_visibility(body.visibility, owner_tenant)
        row.visibility = body.visibility
        if body.visibility == GeneralVisibility.TENANT:
            row.owner_tenant = owner_tenant

    if body.mcp_servers is not None:
        if not body.mcp_servers:
            raise HTTPException(status_code=400, detail="mcp_servers must not be empty")
        for server in body.mcp_servers:
            if not principal.can_access("mcp", server):
                raise HTTPException(
                    status_code=403,
                    detail=f"No access to MCP server '{server}'",
                )

    needs_config_rebuild = any(
        field in update_data
        for field in ("soul", "mcp_servers", "skills", "model", "config")
    )
    if needs_config_rebuild:
        hermes_cfg = row.config.get("hermes", {})
        soul = body.soul.strip() if body.soul is not None else hermes_cfg.get("soul", "")
        if not soul:
            raise HTTPException(status_code=400, detail="soul is required")
        mcp_servers = (
            body.mcp_servers if body.mcp_servers is not None else hermes_cfg.get("mcp_servers", [])
        )
        if not mcp_servers:
            raise HTTPException(status_code=400, detail="mcp_servers must not be empty")
        skills = body.skills if body.skills is not None else hermes_cfg.get("skills", [])
        model = body.model if body.model is not None else hermes_cfg.get("model", "")

        access_token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE)
        if not access_token:
            raise HTTPException(status_code=401, detail="access token required for MCP discovery")

        mcp_tools = await _discover_mcp_tools(settings, access_token, mcp_servers)
        extra_config = body.config if body.config is not None else {
            k: v for k, v in row.config.items() if k != "hermes"
        }
        extra_config.pop("hermes", None)
        config = _build_hermes_config(
            soul,
            mcp_servers,
            mcp_tools,
            skills=skills,
            model=model,
            extra_config=extra_config,
        )
        _validate_config(config)
        row.config = config

    db.add(
        make_audit_row(
            "source_meta.patch_hermes_general",
            principal.user_id,
            principal.sub,
            source_meta_id=id,
            **audit_patch_details(update_data),
        )
    )
    try:
        await db.flush()
        if needs_config_rebuild:
            from hermes_base.vfs_profile import ProfileVfsSync

            vfs_store = getattr(request.app.state, "vfs_agent_store", None)
            if vfs_store is None:
                raise HTTPException(status_code=503, detail="VFS store not configured (set VFS_DSN)")
            vfs_sync = ProfileVfsSync(vfs_store)
            session_dsn = (settings.VFS_DSN or settings.POSTGRES_DSN or "").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            await vfs_sync.seed_from_config(
                row.name,
                row.config,
                session_dsn=session_dsn or None,
            )
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="update conflict") from exc

    log_event(
        "source_meta.patch_hermes_general",
        actor_id=principal.user_id,
        actor=principal.sub,
        source_meta_id=row.id,
        name=row.name,
        version=row.version,
    )
    return _row_to_response(row)
