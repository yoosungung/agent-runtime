"""Tests for chat thread BFF API."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base, SourceMetaRow, UserRow

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_CSRF = "test-csrf-token-value"

_USER_PRINCIPAL = {
    "sub": "alice",
    "user_id": 2,
    "tenant": "dev",
    "access": [{"kind": "agent", "name": "chat-bot"}],
    "grace_applied": False,
    "role": "user",
    "must_change_password": False,
}


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN="sqlite+aiosqlite:///:memory:",
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/backend-test-chat-threads",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture()
async def client(monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
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
        session.add(
            SourceMetaRow(
                id=10,
                kind="agent",
                name="chat-bot",
                version="v1",
                runtime_pool="agent:compiled_graph",
                entrypoint="app:factory",
                bundle_uri="s3://bundles/chat-bot.zip",
            )
        )
        await session.commit()

    from unittest.mock import AsyncMock

    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(
        return_value=Principal.model_validate(_USER_PRINCIPAL),
    )
    app.state.auth_client = mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "tok", "csrf_token": _CSRF},
        headers={"X-CSRF-Token": _CSRF},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_chat_threads(client: AsyncClient) -> None:
    create_resp = await client.post(
        "/api/me/chat/threads",
        json={"agent_name": "chat-bot"},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["agent_name"] == "chat-bot"
    assert created["thread_type"] == "langgraph"
    assert created["title"] == "New Chat"
    assert created["session_id"]
    assert created["id"] != created["session_id"]
    assert created["agent_version"] == "v1"

    list_resp = await client.get("/api/me/chat/threads")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert body["items"][0]["agent_version"] == "v1"
    assert "session_id" not in body["items"][0]


@pytest.mark.asyncio
async def test_create_thread_pins_latest_agent_version(client: AsyncClient) -> None:
    from datetime import UTC, datetime, timedelta

    from backend.app import app

    async with app.state.session_factory() as session:
        session.add(
            SourceMetaRow(
                id=11,
                kind="agent",
                name="chat-bot",
                version="v2",
                runtime_pool="agent:compiled_graph",
                entrypoint="app:factory",
                bundle_uri="s3://bundles/chat-bot-v2.zip",
                created_at=datetime.now(UTC) + timedelta(seconds=10),
            )
        )
        await session.commit()

    create_resp = await client.post(
        "/api/me/chat/threads",
        json={"agent_name": "chat-bot"},
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["agent_version"] == "v2"


@pytest.mark.asyncio
async def test_create_hermes_chat_thread(client: AsyncClient) -> None:
    from backend.app import app

    async with app.state.session_factory() as session:
        session.add(
            SourceMetaRow(
                id=12,
                kind="agent",
                name="hermes-bot",
                version="v1",
                runtime_pool="agent:hermes",
                deploy_mode="hermes_general",
                config={"hermes": {"soul": "hi", "mcp_servers": ["search-server"]}},
            )
        )
        await session.commit()

    prev = app.state.auth_client.verify.return_value
    from runtime_common.schemas import Principal

    app.state.auth_client.verify.return_value = Principal.model_validate(
        {
            **_USER_PRINCIPAL,
            "access": [
                {"kind": "agent", "name": "chat-bot"},
                {"kind": "agent", "name": "hermes-bot"},
            ],
        }
    )
    try:
        create_resp = await client.post(
            "/api/me/chat/threads",
            json={"agent_name": "hermes-bot"},
        )
    finally:
        app.state.auth_client.verify.return_value = prev

    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["thread_type"] == "hermes"


@pytest.mark.asyncio
async def test_create_thread_requires_agent_access(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/me/chat/threads",
        json={"agent_name": "forbidden-agent"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_thread_detail_includes_session_id(client: AsyncClient) -> None:
    created = (await client.post("/api/me/chat/threads", json={"agent_name": "chat-bot"})).json()
    detail = await client.get(f"/api/me/chat/threads/{created['id']}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["session_id"] == created["session_id"]


@pytest.mark.asyncio
async def test_soft_delete_thread(client: AsyncClient) -> None:
    created = (await client.post("/api/me/chat/threads", json={"agent_name": "chat-bot"})).json()
    delete_resp = await client.delete(f"/api/me/chat/threads/{created['id']}")
    assert delete_resp.status_code == 204

    list_resp = await client.get("/api/me/chat/threads")
    assert list_resp.json()["total"] == 0

    detail = await client.get(f"/api/me/chat/threads/{created['id']}")
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_touch_thread_updates_title(client: AsyncClient) -> None:
    created = (await client.post("/api/me/chat/threads", json={"agent_name": "chat-bot"})).json()
    touch_resp = await client.post(
        f"/api/me/chat/threads/{created['id']}/touch",
        json={"title": "Hello world"},
    )
    assert touch_resp.status_code == 200
    assert touch_resp.json()["title"] == "Hello world"

    list_resp = await client.get("/api/me/chat/threads")
    assert list_resp.json()["items"][0]["title"] == "Hello world"


@pytest.mark.asyncio
async def test_get_messages_returns_empty_without_provider_data(client: AsyncClient) -> None:
    created = (await client.post("/api/me/chat/threads", json={"agent_name": "chat-bot"})).json()
    messages_resp = await client.get(f"/api/me/chat/threads/{created['id']}/messages")
    assert messages_resp.status_code == 200
    assert messages_resp.json()["messages"] == []


@pytest.mark.asyncio
async def test_cannot_access_other_users_thread(client: AsyncClient) -> None:
    from backend.app import app
    from runtime_common.schemas import Principal

    created = (await client.post("/api/me/chat/threads", json={"agent_name": "chat-bot"})).json()

    other = {**_USER_PRINCIPAL, "sub": "bob", "user_id": 99}
    app.state.auth_client.verify.return_value = Principal.model_validate(other)

    detail = await client.get(f"/api/me/chat/threads/{created['id']}")
    assert detail.status_code == 404
