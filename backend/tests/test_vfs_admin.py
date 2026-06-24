from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import AuditLogRow, Base, SourceMetaRow

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_CSRF = "test-csrf-token-value"
_ADMIN_PRINCIPAL = {
    "sub": "admin",
    "user_id": 1,
    "tenant": "dev",
    "access": [],
    "grace_applied": False,
    "role": "admin",
    "must_change_password": False,
}
_USER_PRINCIPAL = {**_ADMIN_PRINCIPAL, "role": "user"}


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/vfs-admin-test",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


async def _seed_general_agent(session_factory, *, name: str = "docs-bot") -> None:
    async with session_factory() as session:
        session.add(
            SourceMetaRow(
                kind="agent",
                name=name,
                version="v1",
                runtime_pool="agent:compiled_graph",
                deploy_mode="general",
                visibility="public",
                config={
                    "general": {
                        "system_prompt": "Hi",
                        "mcp_servers": ["s"],
                        "mcp_tools": [],
                        "vfs": {"enabled": True},
                    }
                },
            )
        )
        await session.commit()


@pytest_asyncio.fixture
async def vfs_client(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    import backend.deps as _deps_mod
    from backend.app import app
    from backend.bundle_storage import LocalBundleStorage
    from backend.object_store_browser import LocalObjectStoreBrowser
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal
    from runtime_common.vfs.store import MemoryAgentVfsStore

    storage_dir = tmp_path / "bundles"
    storage_dir.mkdir()

    _settings = _make_test_settings(BUNDLE_STORAGE_DIR=str(storage_dir))
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    bundle_storage = LocalBundleStorage(str(storage_dir))
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage
    app.state.object_store_browser = LocalObjectStoreBrowser(str(storage_dir))
    app.state.vfs_agent_store = MemoryAgentVfsStore()
    app.state.vfs_pool = None

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_ADMIN_PRINCIPAL))
    app.state.auth_client = mock_auth

    from backend.pool_status import PoolRegistryMonitor

    app.state.pool_monitor = PoolRegistryMonitor("")

    await _seed_general_agent(session_factory)

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
async def test_list_vfs_agents(vfs_client: AsyncClient):
    resp = await vfs_client.get("/api/vfs/agents")
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]
    assert len(items) == 1
    assert data["total"] == 1
    assert items[0]["name"] == "docs-bot"
    assert items[0]["vfs_enabled"] is True


@pytest.mark.asyncio
async def test_list_vfs_agents_pagination(vfs_client: AsyncClient):
    from backend.app import app

    for i in range(4):
        await _seed_general_agent(app.state.session_factory, name=f"pag-bot-{i}")

    page1 = await vfs_client.get("/api/vfs/agents", params={"limit": 2, "offset": 0})
    page2 = await vfs_client.get("/api/vfs/agents", params={"limit": 2, "offset": 2})
    assert page1.status_code == 200
    assert page2.status_code == 200
    data1 = page1.json()
    data2 = page2.json()
    assert data1["total"] == 5
    assert len(data1["items"]) == 2
    assert len(data2["items"]) == 2
    names1 = {item["name"] for item in data1["items"]}
    names2 = {item["name"] for item in data2["items"]}
    assert names1.isdisjoint(names2)


@pytest.mark.asyncio
async def test_vfs_file_crud(vfs_client: AsyncClient):
    base = "/api/vfs/agents/agent/docs-bot"

    resp = await vfs_client.put(
        f"{base}/files",
        headers=_csrf_headers(),
        json={"path": "/readme.md", "content": "hello"},
    )
    assert resp.status_code == 201
    assert resp.json()["content"] == "hello"

    resp = await vfs_client.get(f"{base}/entries", params={"path": "/"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert "readme.md" in names

    resp = await vfs_client.get(f"{base}/files", params={"path": "/readme.md"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "hello"

    resp = await vfs_client.patch(
        f"{base}/files",
        headers=_csrf_headers(),
        json={"path": "/readme.md", "content": "updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated"

    resp = await vfs_client.delete(
        f"{base}/files",
        headers=_csrf_headers(),
        params={"path": "/readme.md"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_vfs_create_duplicate_409(vfs_client: AsyncClient):
    base = "/api/vfs/agents/agent/docs-bot"
    payload = {"path": "/dup.txt", "content": "x"}
    assert (
        await vfs_client.put(f"{base}/files", headers=_csrf_headers(), json=payload)
    ).status_code == 201
    resp = await vfs_client.put(f"{base}/files", headers=_csrf_headers(), json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_vfs_path_traversal_400(vfs_client: AsyncClient):
    resp = await vfs_client.put(
        "/api/vfs/agents/agent/docs-bot/files",
        headers=_csrf_headers(),
        json={"path": "/../secret.txt", "content": "nope"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_vfs_unknown_agent_404(vfs_client: AsyncClient):
    resp = await vfs_client.get(
        "/api/vfs/agents/agent/missing-bot/entries",
        params={"path": "/"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_vfs_non_admin_403(vfs_client: AsyncClient):
    from backend.app import app
    from runtime_common.schemas import Principal

    app.state.auth_client.verify.return_value = Principal.model_validate(_USER_PRINCIPAL)
    resp = await vfs_client.get("/api/vfs/agents")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_vfs_write_audit_log(vfs_client: AsyncClient):
    from backend.app import app

    resp = await vfs_client.put(
        "/api/vfs/agents/agent/docs-bot/files",
        headers=_csrf_headers(),
        json={"path": "/audited.txt", "content": "audit"},
    )
    assert resp.status_code == 201

    async with app.state.session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLogRow).where(AuditLogRow.action == "vfs.agent.write")
        )
        rows = list(result.scalars().all())
    assert len(rows) >= 1
    assert rows[-1].details.get("path") == "/audited.txt"


@pytest.mark.asyncio
async def test_vfs_create_folder(vfs_client: AsyncClient):
    resp = await vfs_client.post(
        "/api/vfs/agents/agent/docs-bot/folders",
        headers=_csrf_headers(),
        json={"parent_path": "/", "name": "docs"},
    )
    assert resp.status_code == 201
    assert resp.json()["is_dir"] is True

    resp = await vfs_client.get(
        "/api/vfs/agents/agent/docs-bot/entries",
        params={"path": "/"},
    )
    names = [item["name"] for item in resp.json()["items"]]
    assert "docs" in names
