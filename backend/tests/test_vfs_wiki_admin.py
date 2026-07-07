"""Admin VFS routes for wiki scope."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import AuditLogRow, Base
from runtime_common.vfs.wiki_store import MemoryWikiVfsStore

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
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        PATH_GRAPH_DSN="postgresql://dev/path_graph",
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/vfs-wiki-test",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


def _project_profile():
    profile = MagicMock()
    profile.tenant = "dev"
    profile.id = PROJECT_ID
    profile.slug = "docs"
    profile.name = "Docs"
    return profile


@pytest_asyncio.fixture
async def wiki_vfs_client(tmp_path, monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    _settings = _make_test_settings(BUNDLE_STORAGE_DIR=str(tmp_path / "bundles"))
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.vfs_wiki_store = MemoryWikiVfsStore()

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
async def test_list_wiki_vfs_projects(wiki_vfs_client: AsyncClient):
    store = MagicMock()
    store.list_projects.return_value = [_project_profile()]

    with (
        patch("backend.routers.vfs_user_wiki._project_store", return_value=store),
        patch(
            "backend.routers.vfs_user_wiki.api_get_binding",
            return_value={"wiki": {"vfs_mount": "/wiki/Docs/"}},
        ),
    ):
        resp = await wiki_vfs_client.get("/api/vfs/wiki/projects")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["project_id"] == PROJECT_ID
    assert data["items"][0]["vfs_mount"] == "/wiki/Docs/"


@pytest.mark.asyncio
async def test_wiki_vfs_file_crud(wiki_vfs_client: AsyncClient):
    store = MagicMock()
    store.get_project.return_value = _project_profile()
    base = f"/api/vfs/wiki/projects/{PROJECT_ID}"

    with patch("backend.routers.vfs_user_wiki._project_store", return_value=store):
        resp = await wiki_vfs_client.put(
            f"{base}/files",
            headers=_csrf_headers(),
            json={"path": "/page.md", "content": "# Wiki"},
        )
        assert resp.status_code == 201
        assert resp.json()["content"] == "# Wiki"

        resp = await wiki_vfs_client.get(f"{base}/entries", params={"path": "/"})
        assert resp.status_code == 200
        names = [item["name"] for item in resp.json()["items"]]
        assert "page.md" in names

        resp = await wiki_vfs_client.patch(
            f"{base}/files",
            headers=_csrf_headers(),
            json={"path": "/page.md", "content": "# Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Updated"

        resp = await wiki_vfs_client.delete(
            f"{base}/files",
            headers=_csrf_headers(),
            params={"path": "/page.md"},
        )
        assert resp.status_code == 204


@pytest.mark.asyncio
async def test_wiki_vfs_write_audit_log(wiki_vfs_client: AsyncClient):
    from backend.app import app

    store = MagicMock()
    store.get_project.return_value = _project_profile()

    with patch("backend.routers.vfs_user_wiki._project_store", return_value=store):
        resp = await wiki_vfs_client.put(
            f"/api/vfs/wiki/projects/{PROJECT_ID}/files",
            headers=_csrf_headers(),
            json={"path": "/audited.md", "content": "audit"},
        )
    assert resp.status_code == 201

    async with app.state.session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLogRow).where(AuditLogRow.action == "vfs.wiki.write")
        )
        rows = list(result.scalars().all())
    assert len(rows) >= 1
    assert rows[-1].details.get("path") == "/audited.md"
