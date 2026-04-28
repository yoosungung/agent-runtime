"""Integration tests for deploy-api using SQLite in-memory.

The deploy-api models use PostgreSQL JSONB for the config column.  SQLite
does not have a JSONB type, but SQLAlchemy falls back to JSON serialisation
transparently, so the column stores a text blob.  We patch the column type
at import time so the ORM model works with aiosqlite.

The UserMetaRow.updated_at column has ``onupdate=func.now()`` which in the
async context can trigger ORM lazy-load during UPDATE.  We handle this by
also removing the ``onupdate`` expression from the column at patch time.
"""

from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import runtime_common.db.models as _models

for col in _models.UserMetaRow.__table__.columns:
    if isinstance(col.type, JSONB):
        col.type = JSON()
    if col.name == "updated_at":
        col.onupdate = None

for col in _models.SourceMetaRow.__table__.columns:
    if isinstance(col.type, JSONB):
        col.type = JSON()

from deploy_api.app import _ResolveCache, app  # noqa: E402 — must import after patching
from runtime_common.db.models import Base, SourceMetaRow, UserMetaRow  # noqa: E402

TEST_DSN = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def client():
    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.read_session_factory = session_factory  # same DB in tests
    app.state.resolve_cache = _ResolveCache()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()


_SOURCE_DEFAULTS: dict[str, Any] = {
    "kind": "agent",
    "name": "chat-bot",
    "version": "v1",
    "runtime_pool": "agent:compiled_graph",
    "entrypoint": "app:build_graph",
    "bundle_uri": "s3://bundles/chat-bot-v1.zip",
    "checksum": "sha256:abc123",
}


async def _insert_source(overrides: dict | None = None) -> SourceMetaRow:
    data = {**_SOURCE_DEFAULTS, **(overrides or {})}
    async with app.state.session_factory() as session:
        row = SourceMetaRow(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _insert_user_meta(
    kind: str,
    name: str,
    version: str,
    principal_id: str,
    config: dict,
    secrets_ref: str | None = None,
) -> None:
    async with app.state.session_factory() as session:
        stmt = select(SourceMetaRow).where(
            SourceMetaRow.kind == kind,
            SourceMetaRow.name == name,
            SourceMetaRow.version == version,
        )
        result = await session.execute(stmt)
        source_row = result.scalar_one()
        session.add(
            UserMetaRow(
                source_meta_id=source_row.id,
                principal_id=principal_id,
                config=config,
                secrets_ref=secrets_ref,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# /healthz / /readyz
# ---------------------------------------------------------------------------


async def test_healthz(client: AsyncClient):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz(client: AsyncClient):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /v1/source-meta — list
# ---------------------------------------------------------------------------


async def test_list_source_meta(client: AsyncClient):
    await _insert_source()
    await _insert_source({"name": "other-bot", "version": "v1", "checksum": "sha256:other"})

    resp = await client.get("/v1/source-meta", params={"kind": "agent"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()]
    assert "chat-bot" in names
    assert "other-bot" in names


async def test_list_source_meta_filter_by_name(client: AsyncClient):
    await _insert_source()
    await _insert_source({"name": "other-bot", "version": "v1", "checksum": "sha256:other"})

    resp = await client.get("/v1/source-meta", params={"kind": "agent", "name": "chat-bot"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "chat-bot"


# ---------------------------------------------------------------------------
# /v1/user-meta — get
# ---------------------------------------------------------------------------


async def test_get_user_meta(client: AsyncClient):
    await _insert_source()
    await _insert_user_meta("agent", "chat-bot", "v1", "u_300", {"max_tools": 5})

    resp = await client.get(
        "/v1/user-meta",
        params={"kind": "agent", "name": "chat-bot", "version": "v1", "principal": "u_300"},
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["max_tools"] == 5


async def test_get_user_meta_missing_404(client: AsyncClient):
    await _insert_source()
    resp = await client.get(
        "/v1/user-meta",
        params={"kind": "agent", "name": "chat-bot", "version": "v1", "principal": "nobody"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /v1/resolve
# ---------------------------------------------------------------------------


async def test_resolve_source_only(client: AsyncClient):
    await _insert_source()
    resp = await client.get(
        "/v1/resolve", params={"kind": "agent", "name": "chat-bot", "version": "v1"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"]["name"] == "chat-bot"
    assert data["user"] is None


async def test_resolve_with_user(client: AsyncClient):
    await _insert_source()
    await _insert_user_meta("agent", "chat-bot", "v1", "u_42", {"tone": "formal"})

    resp = await client.get(
        "/v1/resolve",
        params={"kind": "agent", "name": "chat-bot", "version": "v1", "principal": "u_42"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"]["name"] == "chat-bot"
    assert data["user"]["principal_id"] == "u_42"
    assert data["user"]["config"]["tone"] == "formal"


async def test_resolve_latest_version(client: AsyncClient):
    await _insert_source()
    await _insert_source({"version": "v2", "checksum": "sha256:v2hash"})

    resp = await client.get("/v1/resolve", params={"kind": "agent", "name": "chat-bot"})
    assert resp.status_code == 200
    assert resp.json()["source"]["version"] in ("v1", "v2")


async def test_resolve_missing_404(client: AsyncClient):
    resp = await client.get(
        "/v1/resolve", params={"kind": "agent", "name": "nonexistent", "version": "v1"}
    )
    assert resp.status_code == 404


async def test_resolve_returns_etag(client: AsyncClient):
    await _insert_source()
    resp = await client.get(
        "/v1/resolve", params={"kind": "agent", "name": "chat-bot", "version": "v1"}
    )
    assert resp.status_code == 200
    assert "etag" in resp.headers


async def test_resolve_304_on_matching_etag(client: AsyncClient):
    await _insert_source()
    resp = await client.get(
        "/v1/resolve", params={"kind": "agent", "name": "chat-bot", "version": "v1"}
    )
    etag = resp.headers["etag"]

    resp2 = await client.get(
        "/v1/resolve",
        params={"kind": "agent", "name": "chat-bot", "version": "v1"},
        headers={"if-none-match": etag},
    )
    assert resp2.status_code == 304
