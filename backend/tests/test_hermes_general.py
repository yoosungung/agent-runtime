"""Hermes general agent PATCH API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base, SourceMetaRow
from runtime_common.vfs.store import MemoryAgentVfsStore

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
_AGENT = "hermes-patch-bot"


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        BUNDLE_STORAGE_DIR="/tmp/test-bundles-hermes",
        ALLOW_HARD_DELETE=True,
        ENVOY_URL="http://envoy.test",
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


def _mock_mcp_catalog():
    respx.get("http://envoy.test/v1/mcp/servers/search-server/catalog").mock(
        return_value=httpx.Response(
            200,
            json={"tools": [{"name": "search", "description": "Search"}]},
        )
    )


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
    app.state.vfs_agent_store = MemoryAgentVfsStore()
    app.state.vfs_pool = None

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


async def _create_hermes_agent(client: AsyncClient) -> int:
    from backend.app import app
    from runtime_common.schemas import Principal

    _mock_mcp_catalog()
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = Principal.model_validate(
        {**_ADMIN_PRINCIPAL, "access": [{"kind": "mcp", "name": "search-server"}]}
    )
    try:
        resp = await client.post(
            "/api/source-meta/hermes-general",
            headers=_csrf_headers(),
            json={
                "name": _AGENT,
                "version": "v1",
                "soul": "Original soul.",
                "mcp_servers": ["search-server"],
                "skills": ["plan"],
            },
        )
    finally:
        app.state.auth_client.verify.return_value = prev
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
@respx.mock
async def test_patch_hermes_general_updates_soul_and_vfs(client: AsyncClient):
    from backend.app import app
    from hermes_base.vfs_profile import vfs_path

    agent_id = await _create_hermes_agent(client)
    vfs_store = app.state.vfs_agent_store

    _mock_mcp_catalog()
    resp = await client.patch(
        f"/api/source-meta/hermes-general/{agent_id}",
        headers=_csrf_headers(),
        json={"soul": "Updated soul from patch."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["config"]["hermes"]["soul"] == "Updated soul from patch."

    record = await vfs_store.read("agent", _AGENT, vfs_path("SOUL.md"))
    assert record is not None
    assert "Updated soul from patch." in record.content


@pytest.mark.asyncio
@respx.mock
async def test_patch_hermes_general_syncs_skills(client: AsyncClient):
    from backend.app import app
    from hermes_base.vfs_profile import vfs_path

    agent_id = await _create_hermes_agent(client)
    vfs_store = app.state.vfs_agent_store

    _mock_mcp_catalog()
    resp = await client.patch(
        f"/api/source-meta/hermes-general/{agent_id}",
        headers=_csrf_headers(),
        json={"skills": ["search"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["hermes"]["skills"] == ["search"]

    plan = await vfs_store.read("agent", _AGENT, vfs_path("skills/plan.enabled"))
    search = await vfs_store.read("agent", _AGENT, vfs_path("skills/search.enabled"))
    assert plan is None
    assert search is not None


@pytest.mark.asyncio
async def test_patch_hermes_general_rejects_non_hermes(client: AsyncClient):
    from backend.app import app

    async with app.state.session_factory() as session:
        row = SourceMetaRow(
            kind="agent",
            name="general-only",
            version="v1",
            runtime_pool="agent:compiled_graph",
            deploy_mode="general",
            visibility="private",
            config={"general": {"system_prompt": "x", "mcp_servers": ["s"]}},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        general_id = row.id

    resp = await client.patch(
        f"/api/source-meta/hermes-general/{general_id}",
        headers=_csrf_headers(),
        json={"soul": "nope"},
    )
    assert resp.status_code == 400
