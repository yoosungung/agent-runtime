"""Envoy HTTP ext_authz service.

Envoy forwards each client request to this service before routing to a pool.
This service performs:
  1. JWT verify (grace_sec chosen by request path — edge vs internal).
  2. access check against Principal.access.
  3. deploy-api resolve → source.runtime_pool + checksum.
  4. warm-aware scheduler pod pick → pod addr.

Response:
  - 200 + routing headers → Envoy allows and relays the original request to the pool.
    Invoke routes: `x-pod-addr`, `x-principal`, `x-resolve`, …
    MCP stream: `x-pod-addr`, `x-mcp-principal` (Envoy rewrites path to `/mcp`).
  - Non-2xx → Envoy denies; the response body surfaces to the client.

Ext_authz reads the original request body (Envoy buffers up to 64 KiB and forwards it)
to pull out the resource identifier. Response streaming is handled by Envoy passthrough.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NamedTuple

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace

from ext_authz.settings import Settings
from runtime_common.auth import AuthClient
from runtime_common.deploy_client import DeployApiClient
from runtime_common.logging import configure_logging, make_request_id_middleware
from runtime_common.ratelimit import RateLimiter
from runtime_common.registry import RegistryQuery, RegistrySubscriber
from runtime_common.resolve_context import encode_resolve_header
from runtime_common.scheduling import PickResult, Scheduler
from runtime_common.schemas import Principal, parse_runtime_pool
from runtime_common.telemetry import configure_metrics, configure_tracing, get_meter

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("ext-authz")


class _RouteMatch(NamedTuple):
    kind: str
    grace_sec: int
    mode: str  # "invoke" | "stream" | "catalog" | "jobs"


# Path → (kind, grace_mode, mode). Order matters: specific paths before prefixes.
_ROUTE_TABLE: list[tuple[str, str, str, str]] = [
    # grace_mode: "edge" → 0, "internal" → settings.internal_grace_sec
    ("/v1/agents/invoke-internal", "agent", "internal", "invoke"),
    ("/v1/agents/jobs", "agent", "edge", "jobs"),
    ("/v1/agents/invoke", "agent", "edge", "invoke"),
    ("/v1/mcp/invoke-internal", "mcp", "internal", "invoke"),
    ("/v1/mcp/stream", "mcp", "edge", "stream"),
    ("/v1/mcp/invoke", "mcp", "edge", "invoke"),
]


def _parse_mcp_catalog_path(path: str) -> str | None:
    """Return server name from ``/v1/mcp/servers/{name}/catalog``."""
    base = path.split("?", 1)[0]
    prefix = "/v1/mcp/servers/"
    suffix = "/catalog"
    if not base.startswith(prefix) or not base.endswith(suffix):
        return None
    name = base[len(prefix) : -len(suffix)]
    return name if name and "/" not in name else None


def _match_route(path: str, settings: Settings) -> _RouteMatch | None:
    if _parse_mcp_catalog_path(path) is not None:
        return _RouteMatch(kind="mcp", grace_sec=0, mode="catalog")
    for prefix, kind, grace_mode, mode in _ROUTE_TABLE:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            grace = settings.internal_grace_sec if grace_mode == "internal" else 0
            return _RouteMatch(kind=kind, grace_sec=grace, mode=mode)
    return None


def _mcp_relay_headers(
    addr: str,
    fallback: str,
    principal: Principal,
    *,
    grace_sec: int,
    server: str | None = None,
    version: str | None = None,
) -> dict[str, str]:
    headers = {
        "x-pod-addr": addr,
        "x-pod-fallback-addr": fallback,
        "x-mcp-principal": principal.sub,
    }
    if server:
        headers["x-mcp-server"] = server
    if version:
        headers["x-mcp-version"] = version
    if grace_sec > 0 and principal.grace_applied:
        headers["x-grace-applied"] = "1"
    return headers


async def _pick_pool_addr(
    scheduler: Scheduler,
    *,
    runtime_kind: str,
    checksum: str | None,
    ring_key: str,
    pool_url: str,
    kind: str,
) -> tuple[str, str, PickResult]:
    result = await scheduler.pick(
        runtime_kind=runtime_kind,
        checksum=checksum,
        ring_key=ring_key,
        pool_fallback_url=pool_url,
    )
    warm_url = result.url
    addr = _strip_scheme(warm_url) if warm_url else _strip_scheme(pool_url)
    return addr, _strip_scheme(pool_url), result


def _record_pick_metrics(
    *,
    pick_counter: object,
    warm_replicas_hist: object,
    warm_util_hist: object,
    kind: str,
    runtime_kind: str,
    result: PickResult,
) -> None:
    attrs = {"kind": kind, "runtime_kind": runtime_kind, "path": result.path}
    pick_counter.add(1, attrs)  # type: ignore[union-attr]
    if result.warm_replicas > 0:
        dim = {"kind": kind, "runtime_kind": runtime_kind}
        warm_replicas_hist.record(result.warm_replicas, dim)  # type: ignore[union-attr]
        warm_util_hist.record(result.warm_util_max, dim)  # type: ignore[union-attr]


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
        subscriber=agent_subscriber,
        query=query,
        warm_util_threshold=settings.warm_util_threshold,
        warm_target_replicas=settings.warm_target_replicas,
        warm_spill_util=settings.warm_spill_util,
        warm_spill_prob=settings.warm_spill_prob,
    )
    mcp_scheduler = Scheduler(
        kind="mcp",
        subscriber=mcp_subscriber,
        query=query,
        warm_util_threshold=settings.warm_util_threshold,
        warm_target_replicas=settings.warm_target_replicas,
        warm_spill_util=settings.warm_spill_util,
        warm_spill_prob=settings.warm_spill_prob,
    )

    meter = get_meter("ext_authz")
    scheduler_pick_counter = meter.create_counter(
        "scheduler_pick_total",
        description="Scheduler pick outcomes by path",
    )
    scheduler_warm_replicas_hist = meter.create_histogram(
        "scheduler_warm_replicas",
        description="Warm pod count at pick time",
    )
    scheduler_warm_util_hist = meter.create_histogram(
        "scheduler_warm_util_max",
        description="Max warm pod utilization ratio at pick time",
    )

    app.state.settings = settings
    app.state.auth = AuthClient(
        settings.auth_service_url,
        cache_ttl_sec=settings.auth_cache_ttl_sec,
        cache_max=settings.auth_cache_max,
    )
    app.state.deploy = DeployApiClient(
        settings.deploy_api_url,
        cache_ttl_sec=settings.deploy_cache_ttl_sec,
        cache_max=settings.deploy_cache_max,
    )
    app.state.agent_subscriber = agent_subscriber
    app.state.mcp_subscriber = mcp_subscriber
    app.state.query = query
    app.state.agent_scheduler = agent_scheduler
    app.state.mcp_scheduler = mcp_scheduler
    app.state.scheduler_pick_counter = scheduler_pick_counter
    app.state.scheduler_warm_replicas_hist = scheduler_warm_replicas_hist
    app.state.scheduler_warm_util_hist = scheduler_warm_util_hist
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
async def list_servers(request: Request, kind: str | None = None) -> dict:
    """Bearer required. List MCP servers the principal may access (name/version only)."""
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

    allowed = {r.name for r in principal.access if r.kind == "mcp"}
    if not allowed:
        return {"servers": []}

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
        {"name": s.get("name"), "version": s.get("version")}
        for s in resp.json()
        if s.get("name") in allowed
    ]
    return {"servers": servers}


async def _check_mcp_named_server(
    *,
    name: str,
    version: str | None,
    token: str,
    grace_sec: int,
    settings: Settings,
) -> Response:
    with tracer.start_as_current_span("auth.verify") as span:
        span.set_attribute("kind", "mcp")
        span.set_attribute("grace_sec", grace_sec)
        try:
            principal = await app.state.auth.verify(token, grace_sec=grace_sec)
        except Exception as exc:
            span.set_attribute("error", str(exc))
            logger.info("auth_verify_failed", extra={"kind": "mcp", "name": name, "error": str(exc)})
            return _deny(401, "invalid token")

    with tracer.start_as_current_span("access.check") as span:
        span.set_attribute("kind", "mcp")
        span.set_attribute("name", name)
        span.set_attribute("principal", principal.sub)
        if not principal.can_access("mcp", name):
            span.set_attribute("denied", True)
            return _deny(403, f"access denied to mcp {name!r}")

    if not app.state.principal_limiter.allow(principal.sub):
        return _deny(429, "rate limit exceeded for principal")
    if not app.state.resource_limiter.allow(f"mcp:{name}"):
        return _deny(429, "rate limit exceeded for mcp")

    with tracer.start_as_current_span("deploy.resolve") as span:
        span.set_attribute("kind", "mcp")
        span.set_attribute("name", name)
        try:
            resolved = await app.state.deploy.resolve(
                kind="mcp", name=name, version=version, principal=principal.sub
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _deny(404, f"mcp not found: {name}")
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")
        except Exception as exc:
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")

    source = resolved.source
    try:
        pool_id = parse_runtime_pool(source.runtime_pool)
    except ValueError:
        return _deny(502, f"invalid runtime_pool: {source.runtime_pool}")

    if pool_id.is_image_mode:
        pool_url = settings.image_mode_pool_url(pool_id.kind, pool_id.slug)
        addr = _strip_scheme(pool_url)
        return Response(
            status_code=200,
            headers=_mcp_relay_headers(
                addr,
                addr,
                principal,
                grace_sec=grace_sec,
                server=name,
                version=version,
            ),
        )

    pool_url = _pool_url("mcp", pool_id.runtime_kind, settings)
    if not pool_url:
        return _deny(502, f"no pool for runtime_kind: {pool_id.runtime_kind}")

    ring_key = f"mcp:{name}:{version or ''}:{source.checksum or ''}"
    with tracer.start_as_current_span("scheduler.pick") as span:
        span.set_attribute("kind", "mcp")
        span.set_attribute("runtime.pool", source.runtime_pool)
        addr, fallback, pick_result = await _pick_pool_addr(
            app.state.mcp_scheduler,
            runtime_kind=pool_id.runtime_kind,
            checksum=source.checksum,
            ring_key=ring_key,
            pool_url=pool_url,
            kind="mcp",
        )
        span.set_attribute("scheduler.path", pick_result.path)
        _record_pick_metrics(
            pick_counter=app.state.scheduler_pick_counter,
            warm_replicas_hist=app.state.scheduler_warm_replicas_hist,
            warm_util_hist=app.state.scheduler_warm_util_hist,
            kind="mcp",
            runtime_kind=pool_id.runtime_kind,
            result=pick_result,
        )

    return Response(
        status_code=200,
        headers=_mcp_relay_headers(
            addr,
            fallback,
            principal,
            grace_sec=grace_sec,
            server=name,
            version=version,
        ),
    )


async def _check_mcp_catalog(
    request: Request,
    *,
    full_path: str,
    token: str,
    grace_sec: int,
    settings: Settings,
) -> Response:
    name = _parse_mcp_catalog_path(full_path)
    if name is None:
        return _deny(400, "invalid catalog path")
    version = request.query_params.get("version")
    return await _check_mcp_named_server(
        name=name,
        version=version,
        token=token,
        grace_sec=grace_sec,
        settings=settings,
    )


async def _check_mcp_stream(
    request: Request,
    *,
    grace_sec: int,
    token: str,
    settings: Settings,
) -> Response:
    """Authorize MCP stream; Envoy relays the body to pool ``POST /mcp``."""
    name = (request.headers.get("x-mcp-server") or "").strip() or None
    version = request.headers.get("x-mcp-version") or None
    handshake = False

    if name is None:
        raw = await request.body()
        if not raw:
            return _deny(400, "missing request body or X-Mcp-Server header")
        try:
            body_json = json.loads(raw)
        except Exception:
            return _deny(400, "invalid JSON body")
        if body_json.get("method") != "initialize":
            return _deny(400, "missing X-Mcp-Server header")
        handshake = True

    with tracer.start_as_current_span("auth.verify") as span:
        span.set_attribute("kind", "mcp")
        span.set_attribute("grace_sec", grace_sec)
        try:
            principal = await app.state.auth.verify(token, grace_sec=grace_sec)
        except Exception as exc:
            span.set_attribute("error", str(exc))
            logger.info("auth_verify_failed", extra={"kind": "mcp", "name": name, "error": str(exc)})
            return _deny(401, "invalid token")

    if handshake:
        pool_url = settings.pool_fastmcp_url
        addr, fallback, pick_result = await _pick_pool_addr(
            app.state.mcp_scheduler,
            runtime_kind="fastmcp",
            checksum=None,
            ring_key="__mcp_stream_handshake__",
            pool_url=pool_url,
            kind="mcp",
        )
        _record_pick_metrics(
            pick_counter=app.state.scheduler_pick_counter,
            warm_replicas_hist=app.state.scheduler_warm_replicas_hist,
            warm_util_hist=app.state.scheduler_warm_util_hist,
            kind="mcp",
            runtime_kind="fastmcp",
            result=pick_result,
        )
        return Response(
            status_code=200,
            headers=_mcp_relay_headers(addr, fallback, principal, grace_sec=grace_sec),
        )

    return await _check_mcp_named_server(
        name=name,
        version=version,
        token=token,
        grace_sec=grace_sec,
        settings=settings,
    )


def _extract_identifier(body_json: dict[str, Any], kind: str) -> tuple[str | None, str | None]:
    """Return (name, version) from request body for the given kind."""
    if kind == "agent":
        return body_json.get("agent"), body_json.get("version")
    return body_json.get("server"), body_json.get("version")


def _pool_url(kind: str, runtime_kind: str, settings: Settings) -> str | None:
    if kind == "agent":
        return settings.agent_pool_url(runtime_kind)
    return settings.mcp_pool_url(runtime_kind)


async def _check_agent_jobs(
    request: Request,
    *,
    grace_sec: int,
    token: str,
    settings: Settings,
    full_path: str,
) -> Response:
    name = request.headers.get("x-runtime-name") or request.query_params.get("agent")
    version: str | None = request.headers.get("x-runtime-version") or None

    if request.method.upper() == "POST" and not name:
        raw = await request.body()
        if not raw:
            return _deny(400, "missing request body or x-runtime-name header")
        try:
            body_json = json.loads(raw)
        except Exception:
            return _deny(400, "invalid JSON body")
        name, version = _extract_identifier(body_json, "agent")
        if not name:
            return _deny(400, "missing agent field in body")

    if request.method.upper() == "GET" and not name:
        return _deny(400, "missing agent query param or x-runtime-name header")

    with tracer.start_as_current_span("auth.verify") as span:
        span.set_attribute("kind", "agent")
        span.set_attribute("grace_sec", grace_sec)
        try:
            principal = await app.state.auth.verify(token, grace_sec=grace_sec)
        except Exception as exc:
            span.set_attribute("error", str(exc))
            return _deny(401, "invalid token")

    if name and not principal.can_access("agent", name):
        return _deny(403, f"access denied to agent {name!r}")

    if not app.state.principal_limiter.allow(principal.sub):
        return _deny(429, "rate limit exceeded for principal")
    if name and not app.state.resource_limiter.allow(f"agent:{name}"):
        return _deny(429, "rate limit exceeded for agent")

    checksum = None
    runtime_kind = "compiled_graph"
    if name:
        try:
            resolved = await app.state.deploy.resolve(
                kind="agent", name=name, version=version, principal=principal.sub
            )
            pool_id = parse_runtime_pool(resolved.source.runtime_pool)
            runtime_kind = pool_id.runtime_kind
            checksum = resolved.source.checksum
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _deny(404, f"agent not found: {name}")
            return _deny(502, "deploy-api error")
        except Exception:
            return _deny(502, "deploy-api error")

    pool_url = _pool_url("agent", runtime_kind, settings)
    if not pool_url:
        return _deny(502, f"no pool for runtime_kind: {runtime_kind}")

    ring_key = f"agent:{name or 'jobs'}:{version or ''}:{checksum or ''}:{full_path}"
    addr, fallback, pick_result = await _pick_pool_addr(
        app.state.agent_scheduler,
        runtime_kind=runtime_kind,
        checksum=checksum,
        ring_key=ring_key,
        pool_url=pool_url,
        kind="agent",
    )
    _record_pick_metrics(
        pick_counter=app.state.scheduler_pick_counter,
        warm_replicas_hist=app.state.scheduler_warm_replicas_hist,
        warm_util_hist=app.state.scheduler_warm_util_hist,
        kind="agent",
        runtime_kind=runtime_kind,
        result=pick_result,
    )

    principal_b64 = base64.b64encode(principal.model_dump_json().encode("utf-8")).decode("ascii")
    headers = {
        "x-pod-addr": addr,
        "x-pod-fallback-addr": fallback,
        "x-principal": principal_b64,
    }
    if grace_sec > 0 and principal.grace_applied:
        headers["x-grace-applied"] = "1"
    return Response(status_code=200, headers=headers)


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

    # Extract JWT
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return _deny(401, "missing bearer token")
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return _deny(401, "empty bearer token")

    if route.mode == "stream":
        return await _check_mcp_stream(
            request, grace_sec=route.grace_sec, token=token, settings=settings
        )

    if route.mode == "catalog":
        return await _check_mcp_catalog(
            request,
            full_path=full_path,
            token=token,
            grace_sec=route.grace_sec,
            settings=settings,
        )

    if route.mode == "jobs":
        return await _check_agent_jobs(
            request,
            grace_sec=route.grace_sec,
            token=token,
            settings=settings,
            full_path=full_path,
        )

    kind, grace_sec = route.kind, route.grace_sec

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

    # Resolve source meta + user config (pass principal.sub to fetch user_meta)
    with tracer.start_as_current_span("deploy.resolve") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("name", name)
        try:
            resolved = await app.state.deploy.resolve(
                kind=kind, name=name, version=version, principal=principal.sub
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return _deny(404, f"{kind} not found: {name}")
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")
        except Exception as exc:
            logger.warning("deploy_resolve_error", extra={"error": str(exc)})
            return _deny(502, "deploy-api error")

    source = resolved.source
    try:
        pool_id = parse_runtime_pool(source.runtime_pool)
    except ValueError:
        return _deny(502, f"invalid runtime_pool: {source.runtime_pool}")

    principal_b64 = base64.b64encode(principal.model_dump_json().encode("utf-8")).decode("ascii")

    # Build merged config header (source.config + user.config, user wins).
    user_config = resolved.user.config if resolved.user else {}
    merged_cfg = {**source.config, **user_config}
    cfg_b64 = base64.b64encode(
        json.dumps(merged_cfg, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    resolve_b64 = encode_resolve_header(resolved)

    if pool_id.is_image_mode:
        # Image mode: skip warm-registry, derive Service URL from slug.
        pool_url = settings.image_mode_pool_url(pool_id.kind, pool_id.slug)
        addr = _strip_scheme(pool_url)
        resp_headers = {
            "x-pod-addr": addr,
            "x-pod-fallback-addr": addr,
            "x-principal": principal_b64,
            "x-source-version": source.version,
            "x-runtime-cfg": cfg_b64,
            "x-resolve": resolve_b64,
        }
        if resolved.user and resolved.user.secrets_ref:
            resp_headers["x-runtime-secrets-ref"] = resolved.user.secrets_ref
        if grace_sec > 0 and principal.grace_applied:
            resp_headers["x-grace-applied"] = "1"
        return Response(status_code=200, headers=resp_headers)

    # Bundle mode: warm-registry → pool ClusterIP Service fallback
    scheduler: Scheduler = app.state.agent_scheduler if kind == "agent" else app.state.mcp_scheduler
    ring_key = f"{kind}:{name}:{version or ''}:{source.checksum or ''}"
    pool_url = _pool_url(kind, pool_id.runtime_kind, settings)
    if not pool_url:
        return _deny(502, f"no pool for runtime_kind: {pool_id.runtime_kind}")

    with tracer.start_as_current_span("scheduler.pick") as span:
        span.set_attribute("kind", kind)
        span.set_attribute("runtime.pool", source.runtime_pool)
        addr, fallback_addr, pick_result = await _pick_pool_addr(
            scheduler,
            runtime_kind=pool_id.runtime_kind,
            checksum=source.checksum,
            ring_key=ring_key,
            pool_url=pool_url,
            kind=kind,
        )
        span.set_attribute("scheduler.path", pick_result.path)
        _record_pick_metrics(
            pick_counter=app.state.scheduler_pick_counter,
            warm_replicas_hist=app.state.scheduler_warm_replicas_hist,
            warm_util_hist=app.state.scheduler_warm_util_hist,
            kind=kind,
            runtime_kind=pool_id.runtime_kind,
            result=pick_result,
        )

    # ext_authz returns only the host:port pair (no scheme). Envoy's Lua filter
    # replaces :authority with this value; the dynamic_forward_proxy cluster
    # then connects directly to host:port. On retry (x-envoy-attempt-count > 1)
    # the Lua filter switches to x-pod-fallback-addr (pool Service URL).
    resp_headers = {
        "x-pod-addr": addr,
        "x-pod-fallback-addr": fallback_addr,
        "x-principal": principal_b64,
        "x-source-checksum": source.checksum or "",
        "x-source-version": source.version,
        "x-runtime-cfg": cfg_b64,
        "x-resolve": resolve_b64,
    }
    if resolved.user and resolved.user.secrets_ref:
        resp_headers["x-runtime-secrets-ref"] = resolved.user.secrets_ref
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
