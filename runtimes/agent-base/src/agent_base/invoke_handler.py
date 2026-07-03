from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from agent_base.context import reset_current_token, reset_delegate_depth, set_current_token, set_delegate_depth
from agent_base.general_cache import get_or_build_general_agent
from agent_base.knowledge_context import reset_knowledge_bindings, setup_knowledge_bindings
from agent_base.runner import run
from agent_base.settings import Settings
from runtime_common.config_schema import GeneralAgentSourceConfig
from runtime_common.deploy_client import DeployApiClient
from runtime_common.factory import merge_configs
from runtime_common.instance_builder import build_secrets_resolver, get_or_build_cached_instance
from runtime_common.instance_cache import InstanceCache
from runtime_common.loader import BundleFetchError, BundleImportError, BundleLoader
from runtime_common.opik_tracing import opik_trace_context
from runtime_common.pool_resolve import ResolveHeaderMismatchError, resolve_for_invoke
from runtime_common.registry import ActiveCounter
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)


@dataclass
class InvokeContext:
    settings: Settings
    counter: ActiveCounter
    deploy: DeployApiClient
    loader: BundleLoader
    cache: InstanceCache
    vfs_pool: Any
    adk_session_services: dict


async def execute_invoke(
    ctx: InvokeContext,
    *,
    agent: str,
    version: str | None,
    input_data: dict,
    session_id: str | None,
    principal: Principal,
    token: str | None,
    x_resolve: str | None = None,
    delegate_depth: int = 0,
    timeout_sec: int | None = None,
) -> dict[str, Any]:
    settings = ctx.settings
    expected_pool = f"agent:{settings.runtime_kind}"

    tok_token = set_current_token(token)
    depth_token = set_delegate_depth(delegate_depth)
    knowledge_token = None

    try:
        principal_id = str(principal.user_id) if principal.user_id else principal.sub
        try:
            resolved = await resolve_for_invoke(
                ctx.deploy,
                kind="agent",
                name=agent,
                version=version,
                principal=principal_id,
                x_resolve=x_resolve,
            )
        except ResolveHeaderMismatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"resolve failed: {exc}") from exc

        source = resolved.source
        if source.runtime_pool != expected_pool:
            raise HTTPException(
                status_code=400,
                detail=f"pool mismatch: pod hosts {expected_pool}, bundle targets {source.runtime_pool}",
            )

        user = resolved.user
        secrets = build_secrets_resolver(user)
        cfg = merge_configs(source.config, user.config if user else None)

        deploy_mode = getattr(source, "deploy_mode", None) or "bundle"
        if deploy_mode == "general":
            if not principal.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="general agent invoke requires principal.user_id",
                )
            if ctx.vfs_pool is None:
                raise HTTPException(status_code=503, detail="VFS pool not configured (set VFS_DSN)")
            general_cfg = GeneralAgentSourceConfig.model_validate(cfg.get("general") or {})
            admin_url = settings.admin_backend_url
            knowledge_token = await setup_knowledge_bindings(
                tenant=principal.tenant,
                project_ids=general_cfg.knowledge_project_ids,
                admin_backend_url=admin_url,
            )
            try:
                instance = await get_or_build_general_agent(
                    ctx.cache,
                    source,
                    user,
                    secrets,
                    kind=source.kind,
                    agent_name=source.name,
                    user_id=principal.user_id,
                    vfs_pool=ctx.vfs_pool,
                    mcp_gateway_url=settings.mcp_gateway_url,
                    agent_gateway_url=settings.agent_gateway_url or settings.mcp_gateway_url,
                    agent_delegate_timeout_sec=float(settings.agent_delegate_timeout_sec),
                    max_delegate_depth=settings.max_delegate_depth,
                    principal_tenant=principal.tenant,
                    admin_backend_url=admin_url,
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=500, detail=f"general agent build failed: {exc}"
                ) from exc
        else:
            try:
                instance = await get_or_build_cached_instance(
                    ctx.cache, source, user, ctx.loader, secrets
                )
            except BundleFetchError as exc:
                raise HTTPException(status_code=500, detail=f"bundle load failed: {exc}") from exc
            except BundleImportError as exc:
                logger.error("bundle_import_failed", extra={"agent": agent, "error": str(exc)})
                raise HTTPException(status_code=500, detail=f"bundle import failed: {exc}") from exc

        user_id = str(principal.user_id) if principal.user_id else principal.sub
        opik_meta = {"version": version or "latest", "runtime_kind": settings.runtime_kind}
        invoke_timeout = timeout_sec if timeout_sec is not None else settings.invoke_timeout_sec

        try:
            with opik_trace_context(
                name=f"agent:{agent}",
                project_name=agent,
                session_id=session_id,
                user_id=user_id,
                metadata=opik_meta,
            ):
                async with ctx.counter:
                    return await asyncio.wait_for(
                        run(
                            settings.runtime_kind,
                            instance,
                            input_data,
                            session_id,
                            agent_name=agent,
                            cfg=cfg,
                            secrets=secrets,
                            principal_user_id=principal.user_id,
                            adk_session_cache=ctx.adk_session_services,
                        ),
                        timeout=invoke_timeout,
                    )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"invoke timed out after {invoke_timeout}s",
            ) from exc
    finally:
        if knowledge_token is not None:
            reset_knowledge_bindings(knowledge_token)
        reset_current_token(tok_token)
        reset_delegate_depth(depth_token)
