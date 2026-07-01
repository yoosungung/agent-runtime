"""General agent knowledge_project_ids API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
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
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        BUNDLE_STORAGE_DIR="/tmp/test-bundles-general-knowledge",
        ALLOW_HARD_DELETE=True,
        ENVOY_URL="http://envoy.test",
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
@respx.mock
async def test_create_general_agent_stores_knowledge_project_ids(client: AsyncClient):
    from backend.app import app
    from runtime_common.schemas import Principal

    respx.get("http://envoy.test/v1/mcp/servers/rag-server/catalog").mock(
        return_value=httpx.Response(
            200,
            json={"tools": [{"name": "search", "description": "Search knowledge"}]},
        )
    )

    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = Principal.model_validate(
        {**_ADMIN_PRINCIPAL, "access": [{"kind": "mcp", "name": "rag-server"}]}
    )

    mcp_row = MagicMock()
    mcp_row.config = {"knowledge": {"requires_project": True}}

    project_store = MagicMock()
    project_store.get_project.return_value = object()

    with (
        patch("backend.routers.source_meta._pipeline_project_store", return_value=project_store),
        patch(
            "backend.knowledge_validation._latest_mcp_source_meta",
            return_value=mcp_row,
        ),
    ):
        try:
            resp = await client.post(
                "/api/source-meta/general",
                headers=_csrf_headers(),
                json={
                    "name": "kb-bot",
                    "version": "v1",
                    "system_prompt": "Answer from knowledge.",
                    "mcp_servers": ["rag-server"],
                    "knowledge_project_ids": [PROJECT_ID],
                },
            )
        finally:
            app.state.auth_client.verify.return_value = prev

    assert resp.status_code == 201, resp.text
    general = resp.json()["config"]["general"]
    assert general["knowledge_project_ids"] == [PROJECT_ID]
    assert general["mcp_requires_knowledge"] == ["rag-server"]
    project_store.get_project.assert_called_with("dev", PROJECT_ID)
