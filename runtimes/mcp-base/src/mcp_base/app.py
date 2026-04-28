from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from opentelemetry.metrics import Observation
from pydantic import BaseModel

from mcp_base.runner import list_tools as runner_list_tools
from mcp_base.runner import run
from mcp_base.settings import Settings
from runtime_common.deploy_client import DeployApiClient
from runtime_common.factory import call_factory, merge_configs
from runtime_common.loader import BundleFetchError, BundleImportError, BundleLoader
from runtime_common.logging import configure_logging
from runtime_common.opik_tracing import configure_opik, opik_span_context
from runtime_common.registry import ActiveCounter, RegistryPublisher
from runtime_common.schemas import Principal
from runtime_common.secrets import EnvSecretResolver
from runtime_common.telemetry import configure_metrics, configure_tracing, get_meter

logger = logging.getLogger(__name__)


class InvokeRequest(BaseModel):
    server: str
    version: str | None = None
    tool: str
    arguments: dict
    # Phase 1 callers (mcp-gateway) embed Principal in the body.
    # Phase 2 callers (Envoy + ext-authz) pass it as the `x-principal` header.
    principal: Principal | None = None


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

    meter = get_meter("mcp_base")
    meter.create_observable_gauge(
        "pool_active_requests",
        callbacks=[lambda _: [Observation(counter.active)]],
        description="Number of in-flight tool-call requests on this pod",
    )

    addr = f"{settings.pod_ip}:{settings.pod_port}"
    publisher = RegistryPublisher(
        redis_url=settings.redis_url,
        pod_id=settings.pod_name,
        addr=addr,
        runtime_kind=settings.runtime_kind,
        kind="mcp",
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
    try:
        yield
    finally:
        await publisher.stop()
        await deploy_client.aclose()


app = FastAPI(title="mcp-base", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "kind": app.state.settings.runtime_kind}


@app.get("/tools")
async def list_tools(server: str, version: str | None = None) -> dict:
    """List tools exposed by a loaded MCP server bundle.

    Loads the bundle for the given server (using the same BundleLoader cache),
    instantiates the server with no user config, and queries its tool schema.
    Returns {"tools": [...]} where each item has at least "name".
    """
    settings: Settings = app.state.settings
    deploy: DeployApiClient = app.state.deploy
    loader: BundleLoader = app.state.loader

    try:
        resolved = await deploy.resolve(kind="mcp", name=server, version=version)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"resolve failed: {exc}") from exc

    source = resolved.source
    expected_pool = f"mcp:{settings.runtime_kind}"
    if source.runtime_pool != expected_pool:
        raise HTTPException(
            status_code=400,
            detail=f"server {server!r} is hosted by {source.runtime_pool}, not {expected_pool}",
        )

    try:
        factory = loader.load(source)
    except BundleFetchError as exc:
        raise HTTPException(status_code=500, detail=f"bundle load failed: {exc}") from exc
    except BundleImportError as exc:
        logger.error("bundle_import_failed", extra={"server": server, "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"bundle import failed: {exc}") from exc

    secrets = EnvSecretResolver()
    instance = call_factory(factory, source.config, secrets)

    try:
        tools = await runner_list_tools(settings.runtime_kind, instance)
    except Exception as exc:
        logger.warning("tools_list_failed", extra={"server": server, "error": str(exc)})
        tools = []

    return {"tools": tools}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    publisher: RegistryPublisher = app.state.publisher
    if not publisher.healthy():
        raise HTTPException(status_code=503, detail="registry publisher not healthy")
    return {"status": "ok"}


@app.post("/invoke")
async def invoke(
    req: InvokeRequest,
    x_principal: Annotated[str | None, Header()] = None,
) -> dict:
    settings: Settings = app.state.settings
    counter: ActiveCounter = app.state.counter
    deploy: DeployApiClient = app.state.deploy
    loader: BundleLoader = app.state.loader

    expected_pool = f"mcp:{settings.runtime_kind}"

    # Phase 2 (Envoy + ext-authz) delivers Principal via header; Phase 1 (mcp-gateway)
    # via body. Header wins when both are present.
    principal = _principal_from_header(x_principal) or req.principal
    if principal is None:
        raise HTTPException(status_code=401, detail="missing principal")

    # Re-resolve (pool fetches meta itself — trust boundary at deploy-api)
    try:
        resolved = await deploy.resolve(
            kind="mcp",
            name=req.server,
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

    try:
        factory = loader.load(source)
    except BundleFetchError as exc:
        raise HTTPException(status_code=500, detail=f"bundle load failed: {exc}") from exc
    except BundleImportError as exc:
        logger.error("bundle_import_failed", extra={"server": req.server, "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"bundle import failed: {exc}") from exc

    instance = call_factory(factory, merged_cfg, secrets)

    with opik_span_context(
        name=f"mcp:{req.server}/{req.tool}",
        project_name=req.server,
        input_data=req.arguments,
        metadata={"tool": req.tool, "version": req.version or "latest"},
    ) as span:
        async with counter:
            result = await run(settings.runtime_kind, instance, req.tool, req.arguments)
        if span is not None:
            span.update(output=result)

    return result


# ---------------------------------------------------------------------------
# MCP Streamable HTTP transport (MCP 2025 spec)
# POST /mcp  — JSON-RPC 2.0 over HTTP with optional SSE streaming
# ---------------------------------------------------------------------------

_MCP_SERVER_INFO = {"name": "mcp-base", "version": "1.0"}
_MCP_CAPABILITIES: dict[str, dict[str, Any]] = {"tools": {}}


def _jsonrpc_ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _resolve_instance(
    server: str,
    version: str | None,
    principal_sub: str,
    settings: Settings,
    deploy: DeployApiClient,
    loader: BundleLoader,
) -> tuple[Any, str]:
    """Resolve + load bundle; returns (instance, expected_pool)."""
    expected_pool = f"mcp:{settings.runtime_kind}"
    resolved = await deploy.resolve(
        kind="mcp", name=server, version=version, principal=principal_sub
    )
    source = resolved.source
    if source.runtime_pool != expected_pool:
        raise ValueError(f"pool mismatch: {source.runtime_pool} != {expected_pool}")
    user = resolved.user
    user_cfg = user.config if user else {}
    merged_cfg = merge_configs(source.config, user_cfg)
    factory = loader.load(source)
    return call_factory(factory, merged_cfg, EnvSecretResolver()), expected_pool


@app.post("/mcp")
async def mcp_streamable(request: Request) -> Response:
    """MCP Streamable HTTP transport endpoint.

    Accepts JSON-RPC 2.0 requests and responds with:
    - ``application/json`` for non-streaming methods (initialize, tools/list)
    - ``text/event-stream`` SSE for ``tools/call`` when the client sends
      ``Accept: text/event-stream``

    The ``X-Mcp-Server`` and ``X-Mcp-Version`` headers identify the server
    bundle to load (similar to the ``/invoke`` payload).
    """
    settings: Settings = app.state.settings
    counter: ActiveCounter = app.state.counter
    deploy: DeployApiClient = app.state.deploy
    loader: BundleLoader = app.state.loader

    server = request.headers.get("X-Mcp-Server", "")
    version = request.headers.get("X-Mcp-Version") or None
    principal_sub = request.headers.get("X-Mcp-Principal", "anonymous")
    wants_sse = "text/event-stream" in request.headers.get("accept", "")

    try:
        body = await request.json()
    except Exception:
        return Response(
            content=json.dumps(_jsonrpc_err(None, -32700, "parse error")),
            media_type="application/json",
            status_code=400,
        )

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params") or {}

    # --- initialize ---
    if method == "initialize":
        result = {
            "protocolVersion": "2025-03-26",
            "serverInfo": _MCP_SERVER_INFO,
            "capabilities": _MCP_CAPABILITIES,
        }
        return Response(
            content=json.dumps(_jsonrpc_ok(req_id, result)),
            media_type="application/json",
        )

    if not server:
        return Response(
            content=json.dumps(_jsonrpc_err(req_id, -32600, "X-Mcp-Server header required")),
            media_type="application/json",
            status_code=400,
        )

    # --- tools/list ---
    if method == "tools/list":
        try:
            instance, _ = await _resolve_instance(
                server, version, principal_sub, settings, deploy, loader
            )
            tools = await runner_list_tools(settings.runtime_kind, instance)
        except Exception as exc:
            return Response(
                content=json.dumps(_jsonrpc_err(req_id, -32603, str(exc))),
                media_type="application/json",
                status_code=502,
            )
        return Response(
            content=json.dumps(_jsonrpc_ok(req_id, {"tools": tools})),
            media_type="application/json",
        )

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        try:
            instance, _ = await _resolve_instance(
                server, version, principal_sub, settings, deploy, loader
            )
        except Exception as exc:
            return Response(
                content=json.dumps(_jsonrpc_err(req_id, -32603, str(exc))),
                media_type="application/json",
                status_code=502,
            )

        if wants_sse:

            async def _sse_stream():
                async with counter:
                    try:
                        result = await run(settings.runtime_kind, instance, tool_name, arguments)
                        event = _jsonrpc_ok(req_id, result)
                    except Exception as exc:
                        event = _jsonrpc_err(req_id, -32603, str(exc))
                    yield f"data: {json.dumps(event)}\n\n"

            return StreamingResponse(_sse_stream(), media_type="text/event-stream")

        async with counter:
            try:
                result = await run(settings.runtime_kind, instance, tool_name, arguments)
                return Response(
                    content=json.dumps(_jsonrpc_ok(req_id, result)),
                    media_type="application/json",
                )
            except Exception as exc:
                return Response(
                    content=json.dumps(_jsonrpc_err(req_id, -32603, str(exc))),
                    media_type="application/json",
                    status_code=500,
                )

    # --- unknown method ---
    return Response(
        content=json.dumps(_jsonrpc_err(req_id, -32601, f"method not found: {method!r}")),
        media_type="application/json",
        status_code=400,
    )
