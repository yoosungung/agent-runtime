"""MCP source_meta config.knowledge policy tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_ADMIN_PRINCIPAL = {
    "sub": "admin",
    "user_id": 1,
    "tenant": "dev",
    "access": [],
    "grace_applied": False,
    "role": "admin",
    "must_change_password": False,
}
_CSRF = "test-csrf"


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        BUNDLE_STORAGE_DIR="/tmp/test-bundles-mcp-knowledge",
        ALLOW_HARD_DELETE=True,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


@pytest_asyncio.fixture()
async def client(monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from backend.bundle_storage import LocalBundleStorage
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    _settings = _make_test_settings()
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    bundle_storage = LocalBundleStorage(_settings.BUNDLE_STORAGE_DIR)
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_ADMIN_PRINCIPAL))
    app.state.auth_client = mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "valid-token", "csrf_token": _CSRF},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_mcp_bundle_stores_knowledge_requires_project(client: AsyncClient):
    payload = {
        "kind": "mcp",
        "name": "rag-mcp",
        "version": "v1",
        "runtime_pool": "mcp:fastmcp",
        "entrypoint": "app:factory",
        "bundle_uri": "file:///tmp/rag.zip",
        "checksum": "sha256:" + "a" * 64,
        "config": {"knowledge": {"requires_project": True}},
    }
    resp = await client.post("/api/source-meta", headers=_csrf_headers(), json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["knowledge"]["requires_project"] is True


@pytest.mark.asyncio
async def test_create_mcp_bundle_rejects_invalid_knowledge_config(client: AsyncClient):
    payload = {
        "kind": "mcp",
        "name": "bad-mcp",
        "version": "v1",
        "runtime_pool": "mcp:fastmcp",
        "entrypoint": "app:factory",
        "bundle_uri": "file:///tmp/bad.zip",
        "checksum": "sha256:" + "b" * 64,
        "config": {"knowledge": {"requires_project": True, "unknown": True}},
    }
    resp = await client.post("/api/source-meta", headers=_csrf_headers(), json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_mcp_bundle_updates_knowledge_requires_project(client: AsyncClient):
    create = {
        "kind": "mcp",
        "name": "patch-mcp",
        "version": "v1",
        "runtime_pool": "mcp:fastmcp",
        "entrypoint": "app:factory",
        "bundle_uri": "file:///tmp/patch.zip",
        "checksum": "sha256:" + "c" * 64,
        "config": {},
    }
    created = await client.post("/api/source-meta", headers=_csrf_headers(), json=create)
    assert created.status_code == 201
    row_id = created.json()["id"]

    patched = await client.patch(
        f"/api/source-meta/{row_id}",
        headers=_csrf_headers(),
        json={"config": {"knowledge": {"requires_project": True}}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["config"]["knowledge"]["requires_project"] is True
