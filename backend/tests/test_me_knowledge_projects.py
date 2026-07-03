"""Tests for user-facing knowledge project read API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_USER_PRINCIPAL = {
    "sub": "alice",
    "user_id": 2,
    "tenant": "dev",
    "access": [],
    "grace_applied": False,
    "role": "user",
    "must_change_password": False,
}
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        PATH_GRAPH_DSN="postgresql://dev/path_graph",
        BUNDLE_STORAGE_DIR="/tmp/test-me-knowledge-projects",
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture()
async def client(monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    _settings = _make_test_settings()
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_USER_PRINCIPAL))
    app.state.auth_client = mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "valid-token"},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_knowledge_projects_for_user(client: AsyncClient):
    profile = MagicMock()
    profile.tenant = "dev"
    profile.id = PROJECT_ID
    profile.slug = "docs"
    profile.name = "Docs"
    profile.created_at = None

    store = MagicMock()
    store.list_projects.return_value = [profile]

    with patch("backend.routers.me_knowledge_projects.project_store", return_value=store):
        resp = await client.get("/api/me/knowledge-projects")

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == PROJECT_ID
    store.list_projects.assert_called_once_with("dev")


@pytest.mark.asyncio
async def test_get_knowledge_project_binding_for_user(client: AsyncClient):
    store = MagicMock()
    store.get_project.return_value = object()
    binding = {
        "tenant": "dev",
        "project_id": PROJECT_ID,
        "project_slug": "docs",
        "rag": {"index_namespace": "path_graph_dev_col", "filter": {"project_id": PROJECT_ID}},
        "graph": {"nebula_space": "space"},
        "wiki": {"s3_prefix": "wiki/x/", "vfs_mount": "/wiki/docs/"},
    }

    with (
        patch("backend.routers.me_knowledge_projects.project_store", return_value=store),
        patch(
            "backend.pipeline_project_read.api_get_binding",
            return_value=binding,
        ),
    ):
        resp = await client.get(f"/api/me/knowledge-projects/{PROJECT_ID}/binding")

    assert resp.status_code == 200, resp.text
    assert resp.json()["rag"]["index_namespace"] == "path_graph_dev_col"
    store.get_project.assert_called_once_with("dev", PROJECT_ID)


@pytest.mark.asyncio
async def test_knowledge_project_binding_404_for_other_tenant_project(client: AsyncClient):
    store = MagicMock()
    store.get_project.return_value = None

    with patch("backend.routers.me_knowledge_projects.project_store", return_value=store):
        resp = await client.get(f"/api/me/knowledge-projects/{PROJECT_ID}/binding")

    assert resp.status_code == 404
