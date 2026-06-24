"""Tests for /api/me/api-keys BFF."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.auth import AuthClient
from runtime_common.db.models import Base, UserRow
from runtime_common.schemas import Principal

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_CSRF = "test-csrf-token-value"

_USER_PRINCIPAL = Principal(
    sub="alice",
    user_id=2,
    tenant="dev",
    access=[],
    grace_applied=False,
    role="user",
    must_change_password=False,
)


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN="sqlite+aiosqlite:///:memory:",
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/backend-test-me-api-keys",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture()
async def client(monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app

    _settings = _make_test_settings()
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    async with session_factory() as session:
        session.add(
            UserRow(
                id=2,
                username="alice",
                password_hash="x",
                tenant="dev",
                role="user",
            )
        )
        await session.commit()

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=_USER_PRINCIPAL)
    mock_auth.list_api_keys = AsyncMock(
        return_value=[
            {
                "id": 5,
                "name": "laptop",
                "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                "expires_at": None,
                "disabled": False,
            }
        ]
    )
    mock_auth.create_api_key = AsyncMock(
        return_value={"id": 9, "name": "ci", "key": "ak_9_secret"}
    )
    mock_auth.disable_api_key = AsyncMock(return_value=None)
    app.state.auth_client = mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "tok", "csrf_token": _CSRF},
        headers={"X-CSRF-Token": _CSRF},
    ) as ac:
        yield ac, mock_auth

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_my_api_keys(client) -> None:
    ac, mock_auth = client
    resp = await ac.get("/api/me/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "laptop"
    mock_auth.list_api_keys.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_create_my_api_key(client) -> None:
    ac, mock_auth = client
    resp = await ac.post("/api/me/api-keys", json={"name": "ci"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] == "ak_9_secret"
    assert body["name"] == "ci"
    mock_auth.create_api_key.assert_awaited_once_with(
        user_id=2,
        name="ci",
        expires_in_days=None,
    )


@pytest.mark.asyncio
async def test_disable_my_api_key(client) -> None:
    ac, mock_auth = client
    resp = await ac.delete("/api/me/api-keys/5")
    assert resp.status_code == 204
    mock_auth.disable_api_key.assert_awaited_once_with(2, 5)
