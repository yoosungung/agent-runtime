"""Admin VFS routes for user scope."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import AuditLogRow, Base, UserRow
from runtime_common.vfs.store import MemoryUserVfsStore

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


def _csrf_headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/vfs-user-test",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture
async def user_vfs_client(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

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
    app.state.vfs_user_store = MemoryUserVfsStore()
    app.state.vfs_agent_store = None
    app.state.vfs_wiki_store = None

    async with session_factory() as session:
        session.add(
            UserRow(
                id=10,
                username="alice",
                tenant="dev",
                password_hash="x",
                role="user",
            )
        )
        await session.commit()

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
async def test_list_vfs_users(user_vfs_client: AsyncClient):
    resp = await user_vfs_client.get("/api/vfs/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["username"] == "alice"
    assert data["items"][0]["user_id"] == 10


@pytest.mark.asyncio
async def test_user_vfs_file_crud(user_vfs_client: AsyncClient):
    base = "/api/vfs/users/10"

    resp = await user_vfs_client.put(
        f"{base}/files",
        headers=_csrf_headers(),
        json={"path": "/notes.md", "content": "hello"},
    )
    assert resp.status_code == 201
    assert resp.json()["content"] == "hello"

    resp = await user_vfs_client.get(f"{base}/entries", params={"path": "/"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert "notes.md" in names

    resp = await user_vfs_client.patch(
        f"{base}/files",
        headers=_csrf_headers(),
        json={"path": "/notes.md", "content": "updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "updated"

    resp = await user_vfs_client.delete(
        f"{base}/files",
        headers=_csrf_headers(),
        params={"path": "/notes.md"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_user_vfs_write_audit_log(user_vfs_client: AsyncClient):
    from backend.app import app

    resp = await user_vfs_client.put(
        "/api/vfs/users/10/files",
        headers=_csrf_headers(),
        json={"path": "/audited.txt", "content": "audit"},
    )
    assert resp.status_code == 201

    async with app.state.session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AuditLogRow).where(AuditLogRow.action == "vfs.user.write")
        )
        rows = list(result.scalars().all())
    assert len(rows) >= 1
    assert rows[-1].details.get("path") == "/audited.txt"
