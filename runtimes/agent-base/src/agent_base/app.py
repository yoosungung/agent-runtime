from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from opentelemetry.metrics import Observation
from pydantic import BaseModel

from agent_base.context import reset_current_token, reset_delegate_depth, set_current_token, set_delegate_depth
from agent_base.general_cache import get_or_build_general_agent
from agent_base.http_client import close_mcp_http_client
from agent_base.knowledge_context import reset_knowledge_bindings, setup_knowledge_bindings
from agent_base.runner import run, run_stream
from agent_base.settings import Settings
from runtime_common.config_schema import GeneralAgentSourceConfig
from runtime_common.deploy_client import DeployApiClient
from runtime_common.factory import merge_configs
from runtime_common.instance_builder import build_secrets_resolver, get_or_build_cached_instance
from runtime_common.instance_cache import InstanceCache
from runtime_common.loader import BundleFetchError, BundleImportError, BundleLoader
from runtime_common.logging import configure_logging
from runtime_common.opik_tracing import configure_opik, opik_trace_context
from runtime_common.pool_resolve import ResolveHeaderMismatchError, resolve_for_invoke
from runtime_common.providers.pg_infra import close_checkpointer, init_checkpointer
from runtime_common.registry import ActiveCounter, RegistryPublisher
from runtime_common.schemas import Principal
from runtime_common.telemetry import configure_metrics, configure_tracing, get_meter

logger = logging.getLogger(__name__)


class InvokeRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict
    session_id: str | None = None
    # Phase 1 callers (agent-gateway) embed Principal in the body.
    # Phase 2 callers (Envoy + ext-authz) pass it as the `x-principal` header.
    principal: Principal | None = None
    stream: bool = False  # client opt-in for SSE streaming


def _principal_from_header(header_b64: str | None) -> Principal | None:
    if not header_b64:
        return None
    try:
        return Principal.model_validate_json(base64.b64decode(header_b64))
    except Exception as exc:
        logger.warning("x_principal_decode_failed", extra={"error": str(exc)})
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    configure_metrics(settings.service_name, settings.otlp_endpoint)
    configure_opik(settings.opik_url, settings.opik_workspace)

    instance_cache = InstanceCache(settings.instance_cache_max)

    def _on_bundle_evict(checksum: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(instance_cache.invalidate_checksum(checksum))
        except RuntimeError:
            pass

    loader = BundleLoader(
        settings.bundle_cache_dir,
        settings.bundle_cache_max,
        verify_signatures=settings.bundle_verify_signatures,
        signing_public_key=settings.bundle_signing_public_key,
        on_evict=_on_bundle_evict,
    )
    counter = ActiveCounter(settings.max_concurrent)
    deploy_client = DeployApiClient(settings.deploy_api_url)

    vfs_pool = None
    if settings.vfs_dsn:
        from runtime_common.vfs.store import create_asyncpg_pool

        dsn = settings.vfs_dsn.replace("postgresql+asyncpg://", "postgresql://")
        vfs_pool = await create_asyncpg_pool(dsn, pgbouncer=settings.vfs_pgbouncer)

    checkpointer_dsn = settings.checkpointer_dsn or settings.vfs_dsn
    if checkpointer_dsn:
        await init_checkpointer(checkpointer_dsn, pgbouncer=settings.vfs_pgbouncer)

    adk_session_services: dict = {}

    # Expose active_requests as an OTEL gauge so Prometheus/KEDA can scale on it.
    meter = get_meter("agent_base")
    meter.create_observable_gauge(
        "pool_active_requests",
        callbacks=[lambda _: [Observation(counter.active)]],
        description="Number of in-flight invoke requests on this pod",
    )

    addr = f"{settings.pod_ip}:{settings.pod_port}"
    publisher = RegistryPublisher(
        redis_url=settings.redis_url,
        pod_id=settings.pod_name,
        addr=addr,
        runtime_kind=settings.runtime_kind,
        kind="agent",
        active_counter=counter,
        warm_checksums_getter=loader.warm_checksums,
        interval_sec=settings.registry_heartbeat_interval_sec,
        ttl_sec=settings.registry_ttl_sec,
    )

    app.state.settings = settings
    app.state.loader = loader
    app.state.instance_cache = instance_cache
    app.state.counter = counter
    app.state.deploy = deploy_client
    app.state.publisher = publisher
    app.state.vfs_pool = vfs_pool
    app.state.adk_session_services = adk_session_services

    await publisher.start()

    # Warmup: preload frequently-used bundles
    for agent_name in settings.warmup_agents:
        try:
            resolved = await deploy_client.resolve(kind="agent", name=agent_name)
            await loader.aload(resolved.source)
            logger.info("warmup_loaded", extra={"agent": agent_name})
        except Exception as exc:
            logger.warning("warmup_failed", extra={"agent": agent_name, "error": str(exc)})

    try:
        yield
    finally:
        await publisher.stop()
        await close_checkpointer()
        await instance_cache.clear()
        await deploy_client.aclose()
        await close_mcp_http_client()
        if vfs_pool is not None:
            await vfs_pool.close()


app = FastAPI(title="agent-base", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "kind": app.state.settings.runtime_kind}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    publisher: RegistryPublisher = app.state.publisher
    if not publisher.healthy():
        raise HTTPException(status_code=503, detail="registry publisher not healthy")
    return {"status": "ok"}


@app.post("/invoke", response_model=None)
async def invoke(
    req: InvokeRequest,
    authorization: Annotated[str | None, Header()] = None,
    x_principal: Annotated[str | None, Header()] = None,
    x_resolve: Annotated[str | None, Header()] = None,
    x_runtime_delegate_depth: Annotated[str | None, Header(alias="X-Runtime-Delegate-Depth")] = None,
) -> dict | StreamingResponse:
    settings: Settings = app.state.settings
    counter: ActiveCounter = app.state.counter
    deploy: DeployApiClient = app.state.deploy
    loader: BundleLoader = app.state.loader
    cache: InstanceCache = app.state.instance_cache

    expected_pool = f"agent:{settings.runtime_kind}"

    # Phase 2 (Envoy + ext-authz) delivers Principal via header.
    # Phase 1 (agent-gateway) delivers it in the request body. Header wins when both present.
    principal = _principal_from_header(x_principal) or req.principal
    if principal is None:
        raise HTTPException(status_code=401, detail="missing principal")

    # Store JWT for MCP forwarding within this request scope.
    # Streaming sets the token inside the generator (same asyncio context as run_stream).
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    tok_token = None
    depth_token = None
    knowledge_token = None
    delegate_depth = 0
    if x_runtime_delegate_depth:
        try:
            delegate_depth = max(0, int(x_runtime_delegate_depth))
        except ValueError:
            delegate_depth = 0
    if not req.stream:
        tok_token = set_current_token(token)
        depth_token = set_delegate_depth(delegate_depth)

    try:
        # Re-resolve: pool fetches meta itself (trust boundary at deploy-api)
        principal_id = str(principal.user_id) if principal.user_id else principal.sub
        try:
            resolved = await resolve_for_invoke(
                deploy,
                kind="agent",
                name=req.agent,
                version=req.version,
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
                detail=f"pool mismatch: pod hosts {expected_pool}, bundle targets {source.runtime_pool}",  # noqa: E501
            )

        user = resolved.user
        secrets = build_secrets_resolver(user)
        cfg = merge_configs(source.config, user.config if user else None)
        adk_session_cache: dict = app.state.adk_session_services

        deploy_mode = getattr(source, "deploy_mode", None) or "bundle"
        knowledge_token = None
        if deploy_mode == "general":
            if not principal.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="general agent invoke requires principal.user_id",
                )
            vfs_pool = getattr(app.state, "vfs_pool", None)
            if vfs_pool is None:
                raise HTTPException(
                    status_code=503,
                    detail="VFS pool not configured (set VFS_DSN)",
                )
            general_cfg = GeneralAgentSourceConfig.model_validate(cfg.get("general") or {})
            pg_dsn = settings.path_graph_dsn or settings.vfs_dsn
            knowledge_token = await setup_knowledge_bindings(
                tenant=principal.tenant,
                project_ids=general_cfg.knowledge_project_ids,
                path_graph_dsn=pg_dsn,
            )
            try:
                instance = await get_or_build_general_agent(
                    cache,
                    source,
                    user,
                    secrets,
                    kind=source.kind,
                    agent_name=source.name,
                    user_id=principal.user_id,
                    vfs_pool=vfs_pool,
                    mcp_gateway_url=settings.mcp_gateway_url,
                    agent_gateway_url=settings.agent_gateway_url or settings.mcp_gateway_url,
                    agent_delegate_timeout_sec=float(settings.agent_delegate_timeout_sec),
                    max_delegate_depth=settings.max_delegate_depth,
                    principal_tenant=principal.tenant,
                    path_graph_dsn=pg_dsn,
                    wiki_s3_bucket=settings.wiki_s3_bucket,
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=500, detail=f"general agent build failed: {exc}"
                ) from exc
        else:
            try:
                instance = await get_or_build_cached_instance(cache, source, user, loader, secrets)
            except BundleFetchError as exc:
                raise HTTPException(status_code=500, detail=f"bundle load failed: {exc}") from exc
            except BundleImportError as exc:
                logger.error("bundle_import_failed", extra={"agent": req.agent, "error": str(exc)})
                raise HTTPException(status_code=500, detail=f"bundle import failed: {exc}") from exc

        user_id = str(principal.user_id) if principal.user_id else principal.sub
        opik_meta = {"version": req.version or "latest", "runtime_kind": settings.runtime_kind}

        if req.stream:
            async def _stream_with_counter():
                set_current_token(token)
                set_delegate_depth(delegate_depth)
                with opik_trace_context(
                    name=f"agent:{req.agent}",
                    project_name=req.agent,
                    session_id=req.session_id,
                    user_id=user_id,
                    metadata=opik_meta,
                ):
                    async with counter:
                        async for chunk in run_stream(
                            settings.runtime_kind,
                            instance,
                            req.input,
                            req.session_id,
                            agent_name=req.agent,
                            cfg=cfg,
                            secrets=secrets,
                            principal_user_id=principal.user_id,
                            adk_session_cache=adk_session_cache,
                        ):
                            yield chunk

            return StreamingResponse(
                _stream_with_counter(),
                media_type="text/event-stream",
            )

        try:
            with opik_trace_context(
                name=f"agent:{req.agent}",
                project_name=req.agent,
                session_id=req.session_id,
                user_id=user_id,
                metadata=opik_meta,
            ):
                async with counter:
                    result = await asyncio.wait_for(
                        run(
                            settings.runtime_kind,
                            instance,
                            req.input,
                            req.session_id,
                            agent_name=req.agent,
                            cfg=cfg,
                            secrets=secrets,
                            principal_user_id=principal.user_id,
                            adk_session_cache=adk_session_cache,
                        ),
                        timeout=settings.invoke_timeout_sec,
                    )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"invoke timed out after {settings.invoke_timeout_sec}s",
            ) from exc

        return result
    finally:
        if knowledge_token is not None:
            reset_knowledge_bindings(knowledge_token)
        if tok_token is not None:
            reset_current_token(tok_token)
        if depth_token is not None:
            reset_delegate_depth(depth_token)


def get_current_token() -> str | None:
    """Return the JWT for the current request (for MCP JWT forwarding)."""
    from agent_base.context import get_current_token as _get

    return _get()
