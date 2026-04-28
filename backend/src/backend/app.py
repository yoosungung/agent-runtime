from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.bootstrap import run_bootstrap
from backend.bundle_storage import make_bundle_storage
from backend.reconciler import run_reconciler
from backend.routers import audit as audit_router_module
from backend.routers import auth as auth_router_module
from backend.routers import bundles as bundles_router_module
from backend.routers import chat as chat_router_module
from backend.routers import custom_images as custom_images_router_module
from backend.routers import source_meta as source_meta_router_module
from backend.routers import user_meta as user_meta_router_module
from backend.routers import users as users_router_module
from backend.settings import get_settings
from runtime_common.auth import AuthClient
from runtime_common.db import make_engine, make_session_factory, session_scope
from runtime_common.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached static files — adds Cache-Control headers based on path
# ---------------------------------------------------------------------------


class CachedStaticFiles(StaticFiles):
    """StaticFiles subclass that adds Cache-Control headers.

    - assets/ (hashed JS/CSS): public, max-age=31536000, immutable
    - index.html and everything else: no-cache
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_cache(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                path: str = scope.get("path", "")
                headers = MutableHeaders(scope=message)
                if "/assets/" in path:
                    headers.append("Cache-Control", "public, max-age=31536000, immutable")
                else:
                    headers.append("Cache-Control", "no-cache")
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


# ---------------------------------------------------------------------------
# Rate-limiting middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware:
    """Sliding-window rate limiter applied to /api/* routes.

    - Upload paths (e.g. /api/source-meta/bundle): max 5 req/min per key.
    - All other /api/* paths: max 60 req/min per key.
    Key is the access_token cookie value; falls back to client IP.
    Exceeding the limit returns 429 Too Many Requests.
    """

    _UPLOAD_PATHS = {"/api/source-meta/bundle", "/api/source-meta/"}

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._limiter = RateLimiter(max_calls=60, window_sec=60.0)
        self._upload_limiter = RateLimiter(max_calls=5, window_sec=60.0)

    def _is_upload_path(self, path: str) -> bool:
        return path == "/api/source-meta/bundle" or path.endswith("/signature")

    def _get_key(self, scope: Scope) -> str:
        # Prefer access_token cookie as the rate-limit key
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        cookie_header = next((v.decode("latin-1") for k, v in headers if k == b"cookie"), "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("access_token="):
                token = part[len("access_token=") :]
                if token:
                    return f"token:{token[:64]}"
        # Fall back to client IP
        client = scope.get("client")
        if client:
            return f"ip:{client[0]}"
        return "ip:unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not path.startswith("/api/"):
            await self._app(scope, receive, send)
            return

        key = self._get_key(scope)
        limiter = self._upload_limiter if self._is_upload_path(path) else self._limiter

        if not limiter.allow(key):
            body = b'{"detail":"Too Many Requests"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self._app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    engine = make_engine(settings.POSTGRES_DSN, pgbouncer=settings.POSTGRES_PGBOUNCER)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.auth_client = AuthClient(base_url=settings.AUTH_URL)

    # Rate limiters exposed on app.state for testability
    app.state.rate_limiter = RateLimiter(max_calls=60, window_sec=60.0)
    app.state.upload_limiter = RateLimiter(max_calls=5, window_sec=60.0)

    # Initialise bundle storage (local or S3)
    bundle_storage = make_bundle_storage(settings)
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage

    # Bootstrap seed admin
    async with session_scope(app.state.session_factory) as session:
        await run_bootstrap(session, settings)

    # K8s pool manager for custom image mode (optional — skipped if library unavailable)
    app.state.k8s_pool_manager = None
    try:
        from backend.k8s_client import K8sPoolManager, make_api_client
        api_client = await make_api_client(settings)
        app.state.k8s_pool_manager = K8sPoolManager(api_client, settings)
        logger.info("k8s_pool_manager initialised")
    except Exception as exc:
        logger.warning("k8s_pool_manager not available (local dev?): %s", exc)

    # Background reconciler for image-mode state machine
    reconciler_task = asyncio.create_task(run_reconciler(app))

    yield

    reconciler_task.cancel()
    try:
        await reconciler_task
    except asyncio.CancelledError:
        pass

    if app.state.k8s_pool_manager is not None:
        await app.state.k8s_pool_manager.aclose()

    await app.state.auth_client.aclose()
    await engine.dispose()


app = FastAPI(title="admin-console-backend", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Rate limiting (innermost — runs before CORS so CORS headers still appear
# on preflight; add after CORS if you want CORS to wrap rate-limit 429s)
# ---------------------------------------------------------------------------

app.add_middleware(RateLimitMiddleware)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


def _get_cors_origins() -> list[str]:
    settings = get_settings()
    return [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ---------------------------------------------------------------------------
# API routers  — order matters: specific paths before parameterised ones
# ---------------------------------------------------------------------------

app.include_router(auth_router_module.router)  # /api/auth/*
app.include_router(auth_router_module.me_router)  # /api/me
app.include_router(source_meta_router_module.router)  # /api/source-meta/*
app.include_router(user_meta_router_module.router)  # /api/user-meta/*
app.include_router(users_router_module.router)  # /api/users/*
app.include_router(users_router_module.me_router)  # /api/me/password
app.include_router(chat_router_module.router)  # /api/chat/*
app.include_router(audit_router_module.router)  # /api/audit
app.include_router(custom_images_router_module.router)  # /api/admin/custom-images/*

# ---------------------------------------------------------------------------
# Bundle serving (no auth)
# ---------------------------------------------------------------------------

app.include_router(bundles_router_module.router)  # /bundles/*

# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
async def readyz() -> dict[str, str]:
    from sqlalchemy import text

    try:
        async with session_scope(app.state.session_factory) as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=f"DB not ready: {exc}") from exc


# ---------------------------------------------------------------------------
# SPA static file serving (last — must be after all API routes)
# ---------------------------------------------------------------------------


def _maybe_mount_spa() -> None:
    settings = get_settings()
    if not settings.BACKEND_SERVE_SPA:
        return
    dist_dir = Path("dist")
    if not dist_dir.exists():
        logger.info("BACKEND_SERVE_SPA=true but dist/ not found — SPA mount skipped")
        return

    # Hashed assets — long-lived immutable cache
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", CachedStaticFiles(directory=str(assets_dir)), name="assets")

    # Catch-all: serve existing files as-is, everything else → index.html
    from fastapi.responses import FileResponse as FileResponse_  # noqa: N814

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse_:
        candidate = dist_dir / full_path
        target = candidate if candidate.is_file() else dist_dir / "index.html"
        return FileResponse_(str(target))

    logger.info("SPA mounted from %s", dist_dir.resolve())


_maybe_mount_spa()
