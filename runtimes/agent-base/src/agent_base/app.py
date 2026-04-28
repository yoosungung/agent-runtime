from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from opentelemetry.metrics import Observation
from pydantic import BaseModel

from agent_base.runner import run, run_stream
from agent_base.settings import Settings
from runtime_common.deploy_client import DeployApiClient
from runtime_common.factory import call_factory, merge_configs
from runtime_common.loader import BundleFetchError, BundleImportError, BundleLoader
from runtime_common.logging import configure_logging
from runtime_common.opik_tracing import configure_opik, opik_trace_context
from runtime_common.registry import ActiveCounter, RegistryPublisher
from runtime_common.schemas import Principal
from runtime_common.secrets import EnvSecretResolver
from runtime_common.telemetry import configure_metrics, configure_tracing, get_meter

logger = logging.getLogger(__name__)

# Request-scoped bearer token for JWT forwarding to mcp-gateway
_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)


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

    loader = BundleLoader(
        settings.bundle_cache_dir,
        settings.bundle_cache_max,
        verify_signatures=settings.bundle_verify_signatures,
        signing_public_key=settings.bundle_signing_public_key,
    )
    counter = ActiveCounter(settings.max_concurrent)
    deploy_client = DeployApiClient(settings.deploy_api_url)

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
    app.state.counter = counter
    app.state.deploy = deploy_client
    app.state.publisher = publisher

    await publisher.start()

    # Warmup: preload frequently-used bundles
    for agent_name in settings.warmup_agents:
        try:
            resolved = await deploy_client.resolve(kind="agent", name=agent_name)
            loader.load(resolved.source)
            logger.info("warmup_loaded", extra={"agent": agent_name})
        except Exception as exc:
            logger.warning("warmup_failed", extra={"agent": agent_name, "error": str(exc)})

    try:
        yield
    finally:
        await publisher.stop()
        await deploy_client.aclose()


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
) -> dict | StreamingResponse:
    settings: Settings = app.state.settings
    counter: ActiveCounter = app.state.counter
    deploy: DeployApiClient = app.state.deploy
    loader: BundleLoader = app.state.loader

    expected_pool = f"agent:{settings.runtime_kind}"

    # Phase 2 (Envoy + ext-authz) delivers Principal via header.
    # Phase 1 (agent-gateway) delivers it in the request body. Header wins when both present.
    principal = _principal_from_header(x_principal) or req.principal
    if principal is None:
        raise HTTPException(status_code=401, detail="missing principal")

    # Store JWT for MCP forwarding within this request scope
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    tok_token = _current_token.set(token)

    try:
        # Re-resolve: pool fetches meta itself (trust boundary at deploy-api)
        try:
            resolved = await deploy.resolve(
                kind="agent",
                name=req.agent,
                version=req.version,
                principal=str(principal.user_id) if principal.user_id else principal.sub,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"resolve failed: {exc}") from exc

        source = resolved.source
        if source.runtime_pool != expected_pool:
            raise HTTPException(
                status_code=400,
                detail=f"pool mismatch: pod hosts {expected_pool}, bundle targets {source.runtime_pool}",  # noqa: E501
            )

        user = resolved.user
        user_cfg = user.config if user else {}
        merged_cfg = merge_configs(source.config, user_cfg)
        secrets = EnvSecretResolver()

        # Load bundle and get factory
        try:
            factory = loader.load(source)
        except BundleFetchError as exc:
            raise HTTPException(status_code=500, detail=f"bundle load failed: {exc}") from exc
        except BundleImportError as exc:
            logger.error("bundle_import_failed", extra={"agent": req.agent, "error": str(exc)})
            raise HTTPException(status_code=500, detail=f"bundle import failed: {exc}") from exc

        # Instantiate via factory (supports zero-arg, (cfg,), (cfg, secrets))
        instance = call_factory(factory, merged_cfg, secrets)

        user_id = str(principal.user_id) if principal.user_id else principal.sub
        opik_meta = {"version": req.version or "latest", "runtime_kind": settings.runtime_kind}

        if req.stream:
            _saved_tok = tok_token  # capture for generator's finally

            async def _stream_with_counter():
                with opik_trace_context(
                    name=f"agent:{req.agent}",
                    project_name=req.agent,
                    session_id=req.session_id,
                    user_id=user_id,
                    metadata=opik_meta,
                ):
                    try:
                        async with counter:
                            async for chunk in run_stream(
                                settings.runtime_kind,
                                instance,
                                req.input,
                                req.session_id,
                                agent_name=req.agent,
                            ):
                                yield chunk
                    finally:
                        _current_token.reset(_saved_tok)

            tok_token = None  # type: ignore[assignment]  # generator owns reset; skip outer finally
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
        if tok_token is not None:
            _current_token.reset(tok_token)


def get_current_token() -> str | None:
    """Return the JWT for the current request (for MCP JWT forwarding)."""
    return _current_token.get()
