from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from deploy_api.settings import Settings
from runtime_common.db import make_engine, make_session_factory, session_scope
from runtime_common.db.models import Kind, SourceMetaRow, UserMetaRow
from runtime_common.logging import configure_logging
from runtime_common.schemas import ResolveResponse, SourceMeta, UserMeta

_RESOLVE_CACHE_TTL = 5.0
_RESOLVE_CACHE_MAX = 2048


class _ResolveCache:
    """LRU+TTL in-memory cache for /v1/resolve responses."""

    def __init__(self, ttl: float = _RESOLVE_CACHE_TTL, max_size: int = _RESOLVE_CACHE_MAX) -> None:
        self._ttl = ttl
        self._max = max_size
        self._data: OrderedDict[tuple, tuple[str, str, float]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple) -> tuple[str, str] | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            etag, payload, ts = entry
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return etag, payload

    def set(self, key: tuple, etag: str, payload: str) -> None:
        with self._lock:
            self._data[key] = (etag, payload, time.monotonic())
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


def _etag(checksum: str | None, updated_at_epoch: float) -> str:
    return f'W/"{checksum or ""}|{updated_at_epoch:.0f}"'


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(settings.service_name, settings.log_level)
    pgbouncer = settings.postgres_pgbouncer
    engine = make_engine(settings.postgres_dsn, pgbouncer=pgbouncer)
    read_dsn = settings.postgres_read_dsn
    read_engine = make_engine(read_dsn, pgbouncer=pgbouncer) if read_dsn else engine
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.read_session_factory = make_session_factory(read_engine)
    app.state.resolve_cache = _ResolveCache()
    try:
        yield
    finally:
        await engine.dispose()
        if read_engine is not engine:
            await read_engine.dispose()


app = FastAPI(title="deploy-api", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev default; prod에서 override
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# source-meta — read-only (write는 admin 서비스 담당)
# ---------------------------------------------------------------------------


@app.get("/v1/source-meta", response_model=list[SourceMeta])
async def list_source_meta(
    kind: Kind = Query(...),  # noqa: B008
    name: str | None = Query(default=None),  # noqa: B008
) -> list[SourceMeta]:
    async with session_scope(app.state.read_session_factory) as session:
        stmt = select(SourceMetaRow).where(SourceMetaRow.kind == kind.value)
        if name:
            stmt = stmt.where(SourceMetaRow.name == name)
        stmt = stmt.where(
            SourceMetaRow.retired == False,  # noqa: E712
            SourceMetaRow.status != "pending",  # pending rows not yet routable
        )
        stmt = stmt.order_by(SourceMetaRow.created_at.desc())
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [SourceMeta.from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# user-meta — read-only (write는 admin 서비스 담당)
# ---------------------------------------------------------------------------


@app.get("/v1/user-meta", response_model=UserMeta)
async def get_user_meta(
    kind: Kind = Query(...),  # noqa: B008
    name: str = Query(...),  # noqa: B008
    version: str | None = Query(default=None),  # noqa: B008
    principal: str = Query(...),  # noqa: B008
) -> UserMeta:
    async with session_scope(app.state.read_session_factory) as session:
        if version:
            stmt = select(SourceMetaRow).where(
                SourceMetaRow.kind == kind.value,
                SourceMetaRow.name == name,
                SourceMetaRow.version == version,
            )
        else:
            stmt = (
                select(SourceMetaRow)
                .where(SourceMetaRow.kind == kind.value, SourceMetaRow.name == name)
                .order_by(SourceMetaRow.created_at.desc())
                .limit(1)
            )
        result = await session.execute(stmt)
        source_row = result.scalar_one_or_none()
        if source_row is None:
            raise HTTPException(status_code=404, detail=f"{kind}:{name}@{version} not found")

        stmt2 = select(UserMetaRow).where(
            UserMetaRow.source_meta_id == source_row.id,
            UserMetaRow.principal_id == principal,
        )
        result2 = await session.execute(stmt2)
        um_row = result2.scalar_one_or_none()
        if um_row is None:
            raise HTTPException(
                status_code=404, detail=f"user_meta not found for principal {principal!r}"
            )
        return UserMeta.from_row(um_row)


# ---------------------------------------------------------------------------
# /v1/resolve — runtime critical path
# ---------------------------------------------------------------------------


@app.get("/v1/resolve")
async def resolve(
    request: Request,
    kind: Kind = Query(...),  # noqa: B008
    name: str = Query(...),  # noqa: B008
    version: str | None = Query(default=None),  # noqa: B008
    principal: str | None = Query(default=None),  # noqa: B008
) -> Response:
    cache_key = (kind.value, name, version, principal)
    cache: _ResolveCache = app.state.resolve_cache

    cached = cache.get(cache_key)
    if cached is not None:
        etag_value, payload_json = cached
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag_value:
            return Response(status_code=304, headers={"ETag": etag_value})
        return Response(
            content=payload_json,
            media_type="application/json",
            headers={"ETag": etag_value, "Cache-Control": "max-age=5"},
        )

    async with session_scope(app.state.read_session_factory) as session:
        if version:
            stmt = select(SourceMetaRow).where(
                SourceMetaRow.kind == kind.value,
                SourceMetaRow.name == name,
                SourceMetaRow.version == version,
                SourceMetaRow.status != "pending",  # pending rows are not routable
            )
        else:
            stmt = (
                select(SourceMetaRow)
                .where(
                    SourceMetaRow.kind == kind.value,
                    SourceMetaRow.name == name,
                    SourceMetaRow.status != "pending",  # pending rows are not routable
                )
                .order_by(SourceMetaRow.created_at.desc())
                .limit(1)
            )
        result = await session.execute(stmt)
        source_row = result.scalar_one_or_none()
        if source_row is None:
            raise HTTPException(
                status_code=404, detail=f"{kind}:{name}@{version or 'latest'} not found"
            )

        um_row = None
        if principal:
            stmt2 = select(UserMetaRow).where(
                UserMetaRow.source_meta_id == source_row.id,
                UserMetaRow.principal_id == principal,
            )
            result2 = await session.execute(stmt2)
            um_row = result2.scalar_one_or_none()

        source = SourceMeta.from_row(source_row)
        user = UserMeta.from_row(um_row) if um_row is not None else None

        updated_at_epoch = user.updated_at.timestamp() if (user and user.updated_at) else 0.0
        etag_value = _etag(source.checksum, updated_at_epoch)

        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag_value:
            return Response(status_code=304, headers={"ETag": etag_value})

        payload_json = ResolveResponse(source=source, user=user).model_dump_json()
        cache.set(cache_key, etag_value, payload_json)
        return Response(
            content=payload_json,
            media_type="application/json",
            headers={
                "ETag": etag_value,
                "Cache-Control": "max-age=5",
            },
        )
