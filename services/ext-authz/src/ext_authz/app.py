"""Envoy HTTP ext_authz service.

Envoy forwards each client request to this service before routing to a pool.
This service performs:
  1. JWT verify (grace_sec chosen by request path — edge vs internal).
  2. access check against Principal.access.
  3. deploy-api resolve → source.runtime_pool + checksum.
  4. warm-aware scheduler pod pick → pod addr.

Response:
  - 200 + `x-pod-addr: ip:port` + `x-principal: <base64(json)>` → Envoy allows.
    Envoy's `allowed_upstream_headers` config copies these onto the upstream request.
    A downstream Lua filter reads `x-pod-addr` and sets `:authority` so that the
    dynamic_forward_proxy cluster connects to that pod.
  - Non-2xx → Envoy denies; the response body surfaces to the client.

Ext_authz reads the original request body (Envoy buffers up to 8 KiB and forwards it)
to pull out the resource identifier (`agent`/`server`). Body is small for invoke calls;
response streaming is untouched because ext_authz only sees the request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from opentelemetry import trace

from ext_authz.settings import Settings
from runtime_common.auth import AuthClient
from runtime_common.deploy_client import DeployApiClient
from runtime_common.logging import configure_logging, make_request_id_middleware
from runtime_common.ratelimit import RateLimiter
from runtime_common.registry import RegistryQuery, RegistrySubscriber
from runtime_common.scheduling import Scheduler
from runtime_common.schemas import Principal
from runtime_common.telemetry import configure_metrics, configure_tracing

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("ext-authz")


# Path → (kind, grace_sec). Order matters: /invoke-internal before /invoke.
_ROUTE_TABLE: list[tuple[str, str, str]] = [
    # (path_prefix, kind, grace_mode)
    # grace_mode: "edge" → 0, "internal" → settings.mcp_internal_grace_sec
    ("/v1/agents/invoke", "agent", "edge"),
    ("/v1/mcp/invoke-internal", "mcp", "internal"),
    ("/v1/mcp/invoke", "mcp", "edge"),
]


def _match_route(path: str, settings: Settings) -> tuple[str, int] | None:
    for prefix, kind, grace_mode in _ROUTE_TABLE:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            grace = settings.mcp_internal_grace_sec if grace_mode == "internal" else 0
            return kind, grace
    return None


def _deny(status_code: int, detail: str) -> Response:
    return Response(
        content=json.dumps({"detail": detail}),
        media_type="application/json",
        status_code=status_code,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    configure_tracing(settings.service_name, settings.otlp_endpoint)
    configure_metrics(settings.service_name, settings.otlp_endpoint)

    agent_subscriber = RegistrySubscriber(
        redis_url=settings.redis_url,
        kind="agent",
        ttl_sec=float(settings.registry_ttl_sec),
    )
    mcp_subscriber = RegistrySubscriber(
        redis_url=settings.redis_url,
        kind="mcp",
        ttl_sec=float(settings.registry_ttl_sec),
    )
    query = RegistryQuery(redis_url=settings.redis_url)

    await asyncio.gather(agent_subscriber.start(), mcp_subscriber.start())

    agent_scheduler = Scheduler(
        kind="agent",
        ring_fallback_endpoints=[],
        subscriber=agent_subscriber,
        query=query,
    )
    mcp_scheduler = Scheduler(
        kind="mcp",
        ring_fallback_endpoints=[],
        subscriber=mcp_subscriber,
        query=query,
    )

    app.state.settings = settings
    app.state.auth = AuthClient(settings.auth_service_url)
    app.state.deploy = DeployApiClient(settings.deploy_api_url)
    app.state.agent_subscriber = agent_subscriber
    app.state.mcp_subscriber = mcp_subscriber
    app.state.query = query
    app.state.agent_scheduler = agent_scheduler
    app.state.mcp_scheduler = mcp_scheduler
    app.state.principal_limiter = RateLimiter(
        max_calls=settings.rate_limit_per_principal, window_sec=60.0
    )
    app.state.resource_limiter = RateLimiter(
        max_calls=settings.rate_limit_per_resource, window_sec=60.0
    )
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=5.0),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )
    try:
        yield
    finally:
        await asyncio.gather(agent_subscriber.stop(), mcp_subscriber.stop(), return_exceptions=True)
        await query.aclose()
        await app.state.auth.aclose()
        await app.state.deploy.aclose()
        await app.state.http.aclose()


app = FastAPI(title="ext-authz", lifespan=lifespan)
app.add_middleware(make_request_id_middleware())


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> Response:
    agent_sub: RegistrySubscriber = app.state.agent_subscriber
    mcp_sub: RegistrySubscriber = app.state.mcp_subscriber
    if not agent_sub.healthy() or not mcp_sub.healthy():
        return Response(
            content=json.dumps({"detail": "registry subscriber not healthy"}),
            media_type="application/json",
            status_code=503,
        )
    return Response(content='{"status":"ok"}', media_type="application/json")


@app.get("/v1/mcp/servers")
async def list_servers(kind: str | None = None) -> dict:
    """Proxy to deploy-api /v1/source-meta."""
    settings: Settings = app.state.settings
    try:
        resp = await app.state.http.get(
            f"{settings.deploy_api_url}/v1/source-meta",
            params={"kind": kind or "mcp"},
        )
        resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"deploy-api error: {exc}") from exc

    servers = [
        {
            "name": s.get("name"),
            "version": s.get("version"),
            "runtime_pool": s.get("runtime_pool"),
        }
        for s in resp.json()
    ]
    return {"servers": servers}


@app.get("/v1/mcp/servers/{name}/tools")
async def list_server_tools(name: str, request: Request, version: str | None = None) -> dict:
    """Auth required. Resolve → warm pod pick → GET {pod}/tools."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty bearer token")

    try:
        principal = await app.state.auth.verify(token, grace_sec=0)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    if not principal.can_access("mcp", name):
        raise HTTPException(status_code=403, detail=f"access denied to mcp server {name!r}")

    try:
        resolved = await app.state.deploy.resolve(kind="mcp", name=name, version=version)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"mcp server not found: {name}") from exc
        raise HTTPException(status_code=502, detail="deploy-api error") from exc

    source = resolved.source
    _, _, runtime_kind = source.runtime_pool.partition(":")

    settings: Settings = app.state.settings
    warm_url = await app.state.mcp_scheduler.pick(
        runtime_kind=runtime_kind,
        checksum=source.checksum,
        ring_key=f"{name}:{version or ''}:{source.checksum or ''}",
    )
    pool_url = settings.mcp_pool_url(runtime_kind)
    target = warm_url or pool_url
    if not target:
        raise HTTPException(status_code=502, detail=f"no pool for runtime_kind: {runtime_kind}")

    params: dict = {"server": name}
    if version:
        params["version"] = version

    try:
        resp = await app.state.http.get(f"{target}/tools", params=params)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"pool tools error: {exc}") from exc

    return resp.json()


@app.post("/v1/mcp/stream")
async def mcp_stream(request: Request) -> Response:
    """Auth required. X-Mcp-Server header identifies the server. Proxy to pool /mcp."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty bearer token")

    try:
        principal = await app.state.auth.verify(token, grace_sec=0)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    server = request.headers.get("X-Mcp-Server", "")
    version = request.headers.get("X-Mcp-Version") or None
    wants_sse = "text/event-stream" in request.headers.get("accept", "")
    body = await request.body()

    if server:
        if not principal.can_access("mcp", server):
            raise HTTPException(
                status_code=403, detail=f"access denied to mcp server {server!r}"
            )

        if not app.state.principal_limiter.allow(principal.sub):
            raise HTTPException(status_code=429, detail="rate limit exceeded for principal")
        if not app.state.resource_limiter.allow(f"mcp:{server}"):
            raise HTTPException(status_code=429, detail="rate limit exceeded for server")

        with tracer.start_as_current_span("deploy.resolve") as span:
            span.set_attribute("server.name", server)
            try:
                resolved = await app.state.deploy.resolve(
                    kind="mcp", name=server, version=version
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise HTTPException(
                        status_code=404, detail=f"mcp server not found: {server}"
                    ) from exc
                raise HTTPException(status_code=502, detail="deploy-api error") from exc

        source = resolved.source
        _, _, runtime_kind = source.runtime_pool.partition(":")
        settings: Settings = app.state.settings
        warm_url = await app.state.mcp_scheduler.pick(
            runtime_kind=runtime_kind,
            checksum=source.checksum,
            ring_key=f"{server}:{version or ''}:{source.checksum or ''}",
        )
        pool_url = settings.mcp_pool_url(runtime_kind)
        target = warm_url or pool_url
        if not target:
            raise HTTPException(
                status_code=502, detail=f"no pool for runtime_kind: {runtime_kind}"
            )
    else:
        target = None

    if target is None:
        result: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": None,
            "result": {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "ext-authz", "version": "1.0"},
                "capabilities": {"tools": {}},
            },
        }
        try:
            body_json = json.loads(body)
            result["id"] = body_json.get("id")
        except Exception:
            pass
        return Response(content=json.dumps(result), media_type="application/json")

    forward_headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_header:
        forward_headers["Authorization"] = auth_header
    if server:
        forward_headers["X-Mcp-Server"] = server
    if version:
        forward_headers["X-Mcp-Version"] = version
    forward_headers["X-Mcp-Principal"] = principal.sub
    if wants_sse:
        forward_headers["Accept"] = "text/event-stream"

    http = app.state.http

    if wants_sse:

        async def _sse_stream():
            with tracer.start_as_current_span("pool.mcp_stream"):
                async with http.stream(
                    "POST",
                    f"{target}/mcp",
                    content=body,
                    headers=forward_headers,
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes(chunk_size=4096):
                        yield chunk

        return StreamingResponse(_sse_stream(), media_type="text/event-stream")

    with tracer.start_as_current_span("pool.mcp_stream"):
        try:
            resp = await http.post(
                f"{target}/mcp",
                content=body,
                headers=forward_headers,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"pool mcp error: {exc}") from exc

    return Response(content=resp.content, media_type="application/json", status_code=resp.status_code)


def _extract_identifier(body_json: dict[str, Any], kind: str) -> tuple[str | None, str | None]:
    """Return (name, version) from request body for the given kind."""
    if kind == "agent":
        return body_json.get("agent"), body_json.get("version")
    return body_json.get("server"), body_json.get("version")


def _pool_url(kind: str, runtime_kind: str, settings: Settings) -> str | None:
    if kind == "agent":
        return settings.agent_pool_url(runtime_kind)
    return settings.mcp_pool_url(runtime_kind)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def check(path: str, request: Request) -> Response:
    """Envoy ext_authz HTTP check.

    Envoy forwards the original request to us. We inspect headers/path/body
    and return 200 (with `x-pod-addr`, `x-principal` headers) or a 4xx/5xx deny.
    """
    settings: Settings = app.state.settings
    full_path = "/" + path if not path.startswith("/") else path

    route = _match_route(full_path, settings)
    if route is None:
        return _deny(403, f"path not allowed: {full_path}")
    kind, grace_sec = route

    # Extract JWT
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return _deny(401, "missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return _deny(401, "empty bearer token")

    # Resource identifier: x-runtime-name header takes priority over body.
    # Callers (BFF, direct clients) should send x-runtime-name so that Envoy
    # does not need to buffer large bodies just to extract the identifier.
    # Body parsing is kept as a fallback for backward compatibility.
    name = request.headers.get("x-runtime-name")
    version: str | None = request.headers.get("x-runtime-version") or None

    if not name:
        raw = await request.body()
        if not raw:
            return _deny(400, "missing request body or x-runtime-name header")
        try:
            body_json = json.loads(raw)
        except Exception:
            return _deny(400, "invalid JSON body")
        name, version = _extract_identifier(body_json, kind)
        if not name:
            return _deny(400, f"missing {'agent' if kind == 'agent' else 'server'} field in body")

    # Verify token
    with tracer.start_as_current_span("auth.verify") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("grace_sec", grace_sec)
        try:
            principal = await app.state.auth.verify(token, grace_sec=grace_sec)
        except Exception as exc:
            span.set_attribute("error", str(exc))
            logger.info("auth_verify_failed", extra={"kind": kind, "name": name, "error": str(exc)})
            return _deny(401, "invalid token")

    # Access check
    with tracer.start_as_current_span("access.check") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("name", name)
        span.set_attribute("principal", principal.sub)
        if not principal.can_access(kind, name):
            span.set_attribute("denied", True)
            return _deny(403, f"access denied to {kind} {name!r}")

    # Rate limits
    if not app.state.principal_limiter.allow(principal.sub):
        return _deny(429, "rate limit exceeded for principal")
    rate_key = f"{kind}:{name}"
    if not app.state.resource_limiter.allow(rate_key):
        return _deny(429, f"rate limit exceeded for {kind}")

    # Resolve source meta
    with tracer.start_as_current_span("deploy.resolve") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("name", name)
        try:
            resolved = await app.state.deploy.resolve(kind=kind, name=name, version=version)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _deny(404, f"{kind} not found: {name}")
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")
        except Exception as exc:
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")

    source = resolved.source
    _, _, runtime_kind = source.runtime_pool.partition(":")
    if not runtime_kind:
        return _deny(502, f"invalid runtime_pool: {source.runtime_pool}")

    # Pod pick: warm-registry → pull fallback → service URL
    scheduler: Scheduler = app.state.agent_scheduler if kind == "agent" else app.state.mcp_scheduler
    ring_key = f"{kind}:{name}:{version or ''}:{source.checksum or ''}"
    with tracer.start_as_current_span("scheduler.pick") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("runtime.pool", source.runtime_pool)
        warm_url = await scheduler.pick(
            runtime_kind=runtime_kind,
            checksum=source.checksum,
            ring_key=ring_key,
        )

    pool_url = _pool_url(kind, runtime_kind, settings)
    if not pool_url:
        return _deny(502, f"no pool for runtime_kind: {runtime_kind}")

    # ext_authz returns only the host:port pair (no scheme). Envoy's Lua filter
    # replaces :authority with this value; the dynamic_forward_proxy cluster
    # then connects directly to host:port. On retry (x-envoy-attempt-count > 1)
    # the Lua filter switches to x-pod-fallback-addr (pool Service URL).
    addr = _strip_scheme(warm_url) if warm_url else _strip_scheme(pool_url)

    principal_b64 = base64.b64encode(principal.model_dump_json().encode("utf-8")).decode("ascii")

    resp_headers = {
        "x-pod-addr": addr,
        "x-pod-fallback-addr": _strip_scheme(pool_url),
        "x-principal": principal_b64,
        "x-source-checksum": source.checksum or "",
        "x-source-version": source.version,
    }
    if grace_sec > 0 and principal.grace_applied:
        resp_headers["x-grace-applied"] = "1"
        logger.info(
            "grace_applied",
            extra={
                "kind": kind,
                "name": name,
                "principal": principal.sub,
                "path": full_path,
            },
        )
    return Response(status_code=200, headers=resp_headers)


def _strip_scheme(url: str) -> str:
    """Return host[:port] from a URL (or the input if no scheme)."""
    if "://" in url:
        url = url.split("://", 1)[1]
    return url.rstrip("/")


def _principal_from_b64(b64: str) -> Principal:
    """Decode the header set on upstream requests — used by pools."""
    return Principal.model_validate_json(base64.b64decode(b64))
