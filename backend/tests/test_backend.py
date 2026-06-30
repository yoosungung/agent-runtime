"""Integration tests for the admin-console backend (FastAPI BFF).

Uses SQLite in-memory via aiosqlite so no Postgres is needed.
Auth service calls are intercepted with respx.
CSRF validation is bypassed via monkeypatching validate_csrf.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# runtime_common.db.models is already patched by conftest.py
from runtime_common.db.models import Base, SourceMetaRow, UserRow

TEST_DSN = "sqlite+aiosqlite:///:memory:"

# Admin principal JSON returned by the mock auth /verify endpoint
_ADMIN_PRINCIPAL = {
    "sub": "admin",
    "user_id": 1,
    "tenant": "dev",
    "access": [],
    "grace_applied": False,
    "role": "admin",
    "must_change_password": False,
}

# CSRF token used across all state-changing requests
_CSRF = "test-csrf-token-value"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN="sqlite+aiosqlite:///:memory:",
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/backend-test-bundles",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture()
async def client(monkeypatch):
    """Full-stack test client with SQLite DB, mocked auth, and CSRF bypass."""
    import backend.deps as _deps_mod
    from backend.app import app

    # 1. Build test settings and override them via FastAPI's dependency_overrides.
    #    This is the only reliable way: each router imports get_settings by name
    #    so module-level monkeypatching misses them.  dependency_overrides is
    #    checked by FastAPI at call time, bypassing all import aliasing.
    _settings = _make_test_settings()
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings

    # 2. Bypass CSRF — patch the name in deps where check_csrf() calls it
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    # 3. Create SQLite engine and schema
    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    # 4. Set up local bundle storage backed by a temp directory
    from backend.bundle_storage import LocalBundleStorage

    bundle_storage = LocalBundleStorage(_settings.BUNDLE_STORAGE_DIR)
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage
    from backend.object_store_browser import make_object_store_browser

    app.state.object_store_browser = make_object_store_browser(_settings, bundle_storage)

    # 5. Create a mock AuthClient whose verify() always returns admin principal
    from unittest.mock import AsyncMock

    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    mock_auth = AsyncMock(spec=AuthClient)
    admin_principal = Principal.model_validate(_ADMIN_PRINCIPAL)
    mock_auth.verify = AsyncMock(return_value=admin_principal)
    mock_auth.revoke_tokens = AsyncMock(return_value=None)
    mock_auth.refresh = AsyncMock(return_value={"access_token": "new", "refresh_token": "new"})
    mock_auth.logout = AsyncMock(return_value=None)
    # expose the internal _client used by the login route
    mock_auth._client = AsyncMock()
    mock_auth._client.post = AsyncMock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    app.state.auth_client = mock_auth

    from backend.pool_status import PoolRegistryMonitor

    app.state.pool_monitor = PoolRegistryMonitor("")

    # 6. Build the ASGI test client
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "valid-token", _csrf_cookie_name(): _CSRF},
    ) as ac:
        yield ac

    # Teardown
    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


def _csrf_cookie_name() -> str:
    return "csrf_token"


def _csrf_headers() -> dict[str, str]:
    """Return headers needed to pass CSRF check (even though we bypass it)."""
    return {"X-CSRF-Token": _CSRF}


# ---------------------------------------------------------------------------
# Helper: insert source_meta directly into the DB
# ---------------------------------------------------------------------------

_SOURCE_DEFAULTS = {
    "kind": "agent",
    "name": "chat-bot",
    "version": "v1",
    "runtime_pool": "agent:compiled_graph",
    "entrypoint": "app:build_graph",
    "bundle_uri": "s3://bundles/chat-bot-v1.zip",
    "checksum": "sha256:" + "a" * 64,
    "config": {},
    "retired": False,
}


async def _insert_source(app_state, overrides: dict | None = None) -> SourceMetaRow:
    from backend.app import app

    data = {**_SOURCE_DEFAULTS, **(overrides or {})}
    async with app.state.session_factory() as session:
        row = SourceMetaRow(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def _insert_user(
    app_state,
    username: str = "alice",
    role: str = "user",
    tenant: str = "dev",
) -> UserRow:
    from backend.app import app
    from backend.passwords import hash_password

    async with app.state.session_factory() as session:
        row = UserRow(
            username=username,
            password_hash=hash_password("TestPass123!"),
            tenant=tenant,
            disabled=False,
            role=role,
            must_change_password=False,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


# ---------------------------------------------------------------------------
# Health endpoints
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
# source_meta CRUD
# ---------------------------------------------------------------------------

_VALID_SOURCE_BODY = {
    "kind": "agent",
    "name": "chat-bot",
    "version": "v1",
    "runtime_pool": "agent:compiled_graph",
    "entrypoint": "app:build_graph",
    "bundle_uri": "s3://bundles/chat-bot-v1.zip",
    "checksum": "sha256:" + "a" * 64,
    "config": {},
}


async def test_create_source_meta_201(client: AsyncClient):
    resp = await client.post(
        "/api/source-meta",
        json=_VALID_SOURCE_BODY,
        headers=_csrf_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "chat-bot"
    assert data["version"] == "v1"
    assert data["retired"] is False


async def test_create_source_meta_duplicate_409(client: AsyncClient):
    body = _VALID_SOURCE_BODY.copy()
    await client.post("/api/source-meta", json=body, headers=_csrf_headers())
    resp = await client.post("/api/source-meta", json=body, headers=_csrf_headers())
    assert resp.status_code == 409


async def test_create_source_meta_rejects_image_only_runtime_pool(client: AsyncClient):
    body = {
        **_VALID_SOURCE_BODY,
        "kind": "mcp",
        "name": "my-mcp",
        "runtime_pool": "mcp:custom",
    }
    resp = await client.post("/api/source-meta", json=body, headers=_csrf_headers())
    assert resp.status_code == 400
    assert "runtime_pool" in resp.json()["detail"]


async def test_list_source_meta(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state)
    await _insert_source(
        app.state,
        {
            "name": "other-bot",
            "checksum": "sha256:" + "b" * 64,
        },
    )
    resp = await client.get("/api/source-meta", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    names = [item["name"] for item in data["items"]]
    assert "chat-bot" in names
    assert "other-bot" in names


async def test_list_source_meta_filter_kind(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state)
    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "my-mcp",
            "runtime_pool": "mcp:fastmcp",
            "checksum": "sha256:" + "c" * 64,
        },
    )
    resp = await client.get("/api/source-meta", params={"kind": "mcp"}, headers=_csrf_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["kind"] == "mcp" for item in items)


async def test_list_source_meta_filter_deploy_mode(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state, {"name": "bundle-bot", "deploy_mode": "bundle"})
    await _insert_source(
        app.state,
        {
            "name": "general-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:general",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": {"system_prompt": "hi", "mcp_servers": []},
        },
    )
    resp = await client.get(
        "/api/source-meta",
        params={"deploy_mode": "general"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(item["deploy_mode"] == "general" for item in items)
    assert any(item["name"] == "general-bot" for item in items)
    assert all(item["name"] != "bundle-bot" for item in items)


async def test_get_source_meta_by_id(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state)
    resp = await client.get(f"/api/source-meta/{row.id}", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["id"] == row.id


async def test_get_source_meta_not_found(client: AsyncClient):
    resp = await client.get("/api/source-meta/999999", headers=_csrf_headers())
    assert resp.status_code == 404


async def test_retire_source_meta(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state)
    resp = await client.post(f"/api/source-meta/{row.id}/retire", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["retired"] is True


async def test_patch_source_meta_entrypoint(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state)
    resp = await client.patch(
        f"/api/source-meta/{row.id}",
        json={"entrypoint": "app:new_factory"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["entrypoint"] == "app:new_factory"


async def test_delete_source_meta_forbidden_by_default(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state)
    resp = await client.delete(f"/api/source-meta/{row.id}", headers=_csrf_headers())
    assert resp.status_code == 403


async def test_delete_source_meta_with_allow_flag(client: AsyncClient):
    import backend.deps as _deps_mod
    from backend.app import app

    _hard_delete_settings = _make_test_settings(ALLOW_HARD_DELETE=True)
    # Override the FastAPI dependency so the router picks up the new settings
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _hard_delete_settings
    try:
        row = await _insert_source(app.state)
        resp = await client.delete(f"/api/source-meta/{row.id}", headers=_csrf_headers())
        assert resp.status_code == 204

        # Verify it is gone
        resp2 = await client.get(f"/api/source-meta/{row.id}", headers=_csrf_headers())
        assert resp2.status_code == 404
    finally:
        # Restore the default test settings override set by the client fixture
        app.dependency_overrides[_deps_mod.get_settings] = lambda: _make_test_settings()


# ---------------------------------------------------------------------------
# CSRF check — without bypass, a missing header should return 403
# ---------------------------------------------------------------------------


async def test_csrf_missing_header_returns_403(monkeypatch):
    """Real validate_csrf (not bypassed) must reject POST with no CSRF header."""
    import secrets as _secrets_mod

    import backend.deps as _deps_mod

    # Restore the real CSRF logic in deps (undo any prior bypass)
    def _real_validate_csrf(header_value, cookie_value):
        if not header_value or not cookie_value:
            return False
        return _secrets_mod.compare_digest(header_value, cookie_value)

    monkeypatch.setattr(_deps_mod, "validate_csrf", _real_validate_csrf)

    from unittest.mock import AsyncMock

    from backend.app import app
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    # Use dependency_overrides for settings (works regardless of import aliasing)
    _settings = _make_test_settings()
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_ADMIN_PRINCIPAL))
    mock_auth.revoke_tokens = AsyncMock(return_value=None)
    mock_auth._client = AsyncMock()
    app.state.auth_client = mock_auth

    from backend.bundle_storage import LocalBundleStorage

    bundle_storage = LocalBundleStorage(_settings.BUNDLE_STORAGE_DIR)
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage
    from backend.object_store_browser import make_object_store_browser

    app.state.object_store_browser = make_object_store_browser(_settings, bundle_storage)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            # access_token present but NO csrf cookie and NO X-CSRF-Token header
            cookies={"access_token": "valid-token"},
        ) as ac:
            resp = await ac.post("/api/source-meta", json=_VALID_SOURCE_BODY)
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(_deps_mod.get_settings, None)
        await engine.dispose()


# ---------------------------------------------------------------------------
# users CRUD
# ---------------------------------------------------------------------------


async def test_create_user_201(client: AsyncClient):
    resp = await client.post(
        "/api/users",
        json={
            "username": "bob",
            "password": "StrongPassword123!",
            "tenant": "dev",
            "role": "user",
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "bob"
    assert data["role"] == "user"


async def test_create_user_weak_password_400(client: AsyncClient):
    resp = await client.post(
        "/api/users",
        json={"username": "carol", "password": "short", "tenant": "dev"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 400


async def test_create_user_duplicate_409(client: AsyncClient):
    body = {"username": "dave", "password": "StrongPassword123!", "tenant": "dev", "role": "user"}
    await client.post("/api/users", json=body, headers=_csrf_headers())
    resp = await client.post("/api/users", json=body, headers=_csrf_headers())
    assert resp.status_code == 409


async def test_list_users(client: AsyncClient):
    from backend.app import app

    await _insert_user(app.state, "user-alpha")
    await _insert_user(app.state, "user-beta")
    resp = await client.get("/api/users", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    usernames = [u["username"] for u in data["items"]]
    assert "user-alpha" in usernames
    assert "user-beta" in usernames


async def test_get_user_by_id(client: AsyncClient):
    from backend.app import app

    row = await _insert_user(app.state, "charlie")
    resp = await client.get(f"/api/users/{row.id}", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["username"] == "charlie"


async def test_get_user_not_found(client: AsyncClient):
    resp = await client.get("/api/users/999999", headers=_csrf_headers())
    assert resp.status_code == 404


async def test_patch_user_tenant(client: AsyncClient):

    from backend.app import app

    row = await _insert_user(app.state, "patch-me")

    # patch_user also calls get_principal internally — make sure it still works
    resp = await client.patch(
        f"/api/users/{row.id}",
        json={"tenant": "acme"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["tenant"] == "acme"


async def test_grant_user_access(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(app.state)
    user = await _insert_user(app.state, "grant-user")

    resp = await client.post(
        f"/api/users/{user.id}/access",
        json={"kind": source.kind, "name": source.name},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 204


async def test_grant_user_access_idempotent(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(app.state)
    user = await _insert_user(app.state, "idempotent-user")

    payload = {"kind": source.kind, "name": source.name}
    await client.post(f"/api/users/{user.id}/access", json=payload, headers=_csrf_headers())
    resp = await client.post(f"/api/users/{user.id}/access", json=payload, headers=_csrf_headers())
    assert resp.status_code == 204


async def test_list_user_access(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(app.state)
    user = await _insert_user(app.state, "list-access-user")

    await client.post(
        f"/api/users/{user.id}/access",
        json={"kind": source.kind, "name": source.name},
        headers=_csrf_headers(),
    )

    resp = await client.get(f"/api/users/{user.id}/access", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["kind"] == source.kind
    assert data["items"][0]["name"] == source.name


async def test_revoke_user_access(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(app.state)
    user = await _insert_user(app.state, "revoke-user")

    await client.post(
        f"/api/users/{user.id}/access",
        json={"kind": source.kind, "name": source.name},
        headers=_csrf_headers(),
    )

    resp = await client.delete(
        f"/api/users/{user.id}/access",
        params={"kind": source.kind, "name": source.name},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 204

    # Verify it's gone
    check = await client.get(f"/api/users/{user.id}/access", headers=_csrf_headers())
    assert check.json()["total"] == 0


async def test_revoke_user_access_not_found_404(client: AsyncClient):
    from backend.app import app

    user = await _insert_user(app.state, "revoke-none-user")
    resp = await client.delete(
        f"/api/users/{user.id}/access",
        params={"kind": "agent", "name": "nonexistent"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 404


async def test_delete_user(client: AsyncClient):
    from backend.app import app

    # SQLite auto-increments from 1. The mock principal has user_id=1, so the
    # first user inserted would collide ("Cannot delete your own account").
    # Insert a placeholder user first so the target gets a higher id.
    await _insert_user(app.state, "placeholder-admin", role="admin")
    target = await _insert_user(app.state, "delete-target")

    resp = await client.delete(f"/api/users/{target.id}", headers=_csrf_headers())
    assert resp.status_code == 204

    check = await client.get(f"/api/users/{target.id}", headers=_csrf_headers())
    assert check.status_code == 404


async def test_delete_user_not_found(client: AsyncClient):
    resp = await client.delete("/api/users/999999", headers=_csrf_headers())
    assert resp.status_code == 404


async def test_grant_access_nonexistent_source_meta_404(client: AsyncClient):
    from backend.app import app

    user = await _insert_user(app.state, "no-source-user")
    resp = await client.post(
        f"/api/users/{user.id}/access",
        json={"kind": "agent", "name": "doesnt-exist"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# source_meta access list
# ---------------------------------------------------------------------------


async def test_get_source_meta_access_list(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(app.state)
    user = await _insert_user(app.state, "sm-access-user")

    await client.post(
        f"/api/users/{user.id}/access",
        json={"kind": source.kind, "name": source.name},
        headers=_csrf_headers(),
    )

    resp = await client.get(f"/api/source-meta/{source.id}/access", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["username"] == "sm-access-user"


# ---------------------------------------------------------------------------
# source_meta pagination
# ---------------------------------------------------------------------------


async def test_list_source_meta_pagination(client: AsyncClient):
    from backend.app import app

    checksums = ["sha256:" + str(i) * 64 for i in range(5)]
    for i, cs in enumerate(checksums):
        await _insert_source(app.state, {"name": f"paginated-bot-{i}", "checksum": cs})

    resp = await client.get(
        "/api/source-meta",
        params={"limit": 2, "offset": 0, "name": "paginated-bot"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 2
    assert len(data["items"]) == 2
    assert data["total"] == 5


# ---------------------------------------------------------------------------
# user_meta CRUD
# ---------------------------------------------------------------------------


async def test_upsert_user_meta_email_config_validated(client: AsyncClient):
    """PUT /api/user-meta validates email user sections."""
    from backend.app import app

    source = await _insert_source(
        app.state, {"name": "email-server", "checksum": "sha256:" + "f" * 64}
    )
    resp = await client.put(
        "/api/user-meta",
        json={
            "source_meta_id": source.id,
            "principal_id": "hong",
            "config": {
                "email": {"from_address": "hong@company.com"},
                "outlook": {"mailbox": "hong@company.com", "refresh_token": "rt-1"},
            },
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["config"]["email"]["from_address"] == "hong@company.com"
    assert data["config"]["outlook"]["mailbox"] == "hong@company.com"


async def test_upsert_user_meta_create(client: AsyncClient):
    """PUT /api/user-meta creates a new record."""
    from backend.app import app

    source = await _insert_source(app.state)
    resp = await client.put(
        "/api/user-meta",
        json={
            "source_meta_id": source.id,
            "principal_id": "user-alice",
            "config": {"model": "gpt-4"},
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["principal_id"] == "user-alice"
    assert data["config"] == {"model": "gpt-4"}


async def test_upsert_user_meta_update(client: AsyncClient):
    """PUT /api/user-meta updates existing record idempotently."""
    from backend.app import app

    source = await _insert_source(
        app.state, {"name": "um-update-bot", "checksum": "sha256:" + "e" * 64}
    )
    payload = {"source_meta_id": source.id, "principal_id": "user-bob", "config": {"v": 1}}
    await client.put("/api/user-meta", json=payload, headers=_csrf_headers())
    payload["config"] = {"v": 2}
    resp = await client.put("/api/user-meta", json=payload, headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["config"] == {"v": 2}


async def test_list_user_meta(client: AsyncClient):
    """GET /api/user-meta returns list filtered by source_meta_id."""
    from backend.app import app

    source = await _insert_source(
        app.state, {"name": "um-list-bot", "checksum": "sha256:" + "f" * 64}
    )
    await client.put(
        "/api/user-meta",
        json={"source_meta_id": source.id, "principal_id": "list-user", "config": {}},
        headers=_csrf_headers(),
    )
    resp = await client.get(
        "/api/user-meta",
        params={"source_meta_id": source.id},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(item["principal_id"] == "list-user" for item in data["items"])


async def test_delete_user_meta(client: AsyncClient):
    """DELETE /api/user-meta/{id} removes the record."""
    from backend.app import app

    source = await _insert_source(
        app.state, {"name": "um-del-bot", "checksum": "sha256:" + "d" * 64}
    )
    create_resp = await client.put(
        "/api/user-meta",
        json={"source_meta_id": source.id, "principal_id": "del-user", "config": {}},
        headers=_csrf_headers(),
    )
    um_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/user-meta/{um_id}", headers=_csrf_headers())
    assert resp.status_code == 204
    # Confirm gone
    list_resp = await client.get(
        "/api/user-meta",
        params={"source_meta_id": source.id},
        headers=_csrf_headers(),
    )
    ids = [i["id"] for i in list_resp.json()["items"]]
    assert um_id not in ids


async def test_upsert_user_meta_source_not_found_404(client: AsyncClient):
    resp = await client.put(
        "/api/user-meta",
        json={"source_meta_id": 999999, "principal_id": "ghost", "config": {}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# user_meta_template on source_meta
# ---------------------------------------------------------------------------


async def test_patch_source_meta_user_meta_template(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state, {"kind": "mcp", "name": "email-server"})
    template = {
        "description": "Connect your mailbox",
        "fields": [
            {
                "path": "outlook.mailbox",
                "label": "Mailbox",
                "type": "string",
                "required": True,
            }
        ],
        "secrets_ref_enabled": False,
    }
    resp = await client.patch(
        f"/api/source-meta/{row.id}",
        json={"user_meta_template": template},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["user_meta_template"]["description"] == "Connect your mailbox"
    assert len(resp.json()["user_meta_template"]["fields"]) == 1


async def test_patch_source_meta_user_meta_template_disabled(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state, {"kind": "mcp", "name": "utility-server"})
    resp = await client.patch(
        f"/api/source-meta/{row.id}",
        json={"user_meta_template": {"enabled": False}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["user_meta_template"]["enabled"] is False


async def test_patch_source_meta_user_meta_template_invalid(client: AsyncClient):
    from backend.app import app

    row = await _insert_source(app.state)
    resp = await client.patch(
        f"/api/source-meta/{row.id}",
        json={"user_meta_template": {"fields": [{"path": "", "label": "x"}]}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/me/user-meta self-service
# ---------------------------------------------------------------------------


def _user_principal(username: str = "alice", access: list | None = None):
    from runtime_common.schemas import Principal, ResourceRef

    refs = [ResourceRef.model_validate(item) for item in (access or [])]
    return Principal(
        sub=username,
        user_id=2,
        tenant=None,
        access=refs,
        grace_applied=False,
        role="user",
        must_change_password=False,
    )


async def test_me_user_meta_forbidden_without_access(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state, {"kind": "mcp", "name": "email-server"})
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal("alice", [])
    try:
        resp = await client.get(
            "/api/me/user-meta",
            params={"kind": "mcp", "name": "email-server"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 403
    finally:
        app.state.auth_client.verify.return_value = prev


async def test_me_user_meta_upsert_and_get(client: AsyncClient):
    from backend.app import app

    source = await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "email-server",
            "user_meta_template": {
                "fields": [
                    {
                        "path": "email.from_address",
                        "label": "From",
                        "required": True,
                    }
                ]
            },
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "alice",
        [{"kind": "mcp", "name": "email-server"}],
    )
    try:
        put_resp = await client.put(
            "/api/me/user-meta",
            json={
                "kind": "mcp",
                "name": "email-server",
                "config": {"email": {"from_address": "alice@company.com"}},
            },
            headers=_csrf_headers(),
        )
        assert put_resp.status_code == 200
        data = put_resp.json()
        assert data["config"]["email"]["from_address"] == "alice@company.com"
        assert data["source_meta_id"] == source.id

        get_resp = await client.get(
            "/api/me/user-meta",
            params={"kind": "mcp", "name": "email-server"},
            headers=_csrf_headers(),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["config"]["email"]["from_address"] == "alice@company.com"
    finally:
        app.state.auth_client.verify.return_value = prev


async def test_me_access_resources(client: AsyncClient):
    from backend.app import app

    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "search-server",
            "user_meta_template": {"description": "No keys needed"},
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "bob",
        [{"kind": "mcp", "name": "search-server"}],
    )
    try:
        resp = await client.get(
            "/api/me/access-resources",
            params={"kind": "mcp"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "search-server"
        assert items[0]["template_description"] == "No keys needed"
        assert items[0]["user_meta_required"] is False
    finally:
        app.state.auth_client.verify.return_value = prev


async def test_me_access_resources_user_meta_not_required(client: AsyncClient):
    from backend.app import app

    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "utility-server",
            "user_meta_template": {"enabled": False},
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "bob",
        [{"kind": "mcp", "name": "utility-server"}],
    )
    try:
        resp = await client.get(
            "/api/me/access-resources",
            params={"kind": "mcp"},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["user_meta_required"] is False
    finally:
        app.state.auth_client.verify.return_value = prev


async def test_me_user_meta_upsert_rejected_when_not_required(client: AsyncClient):
    from backend.app import app

    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "utility-server",
            "user_meta_template": {"enabled": False},
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "alice",
        [{"kind": "mcp", "name": "utility-server"}],
    )
    try:
        resp = await client.put(
            "/api/me/user-meta",
            json={"kind": "mcp", "name": "utility-server", "config": {}},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 400
        assert "not required" in resp.json()["detail"].lower()
    finally:
        app.state.auth_client.verify.return_value = prev


async def test_me_user_meta_required_field_validation(client: AsyncClient):
    from backend.app import app

    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "email-server",
            "user_meta_template": {
                "fields": [
                    {
                        "path": "outlook.mailbox",
                        "label": "Mailbox",
                        "required": True,
                    }
                ]
            },
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "alice",
        [{"kind": "mcp", "name": "email-server"}],
    )
    try:
        resp = await client.put(
            "/api/me/user-meta",
            json={"kind": "mcp", "name": "email-server", "config": {}},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 400
        assert "outlook.mailbox" in resp.json()["detail"]
    finally:
        app.state.auth_client.verify.return_value = prev


# ---------------------------------------------------------------------------
# infra_meta
# ---------------------------------------------------------------------------


async def test_get_infra_meta_empty(client: AsyncClient):
    resp = await client.get("/api/infra-meta", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "global"
    assert data["env"] == {}
    assert data["secret_keys"] == []


async def test_upsert_infra_meta_env(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"env": {"OPIK_URL": "http://opik:5173/api", "OPIK_WORKSPACE": "dev"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["env"]["OPIK_URL"] == "http://opik:5173/api"
    assert data["reconciled"] is False


async def test_upsert_infra_meta_env_merge_preserves_extra(client: AsyncClient):
    await client.put(
        "/api/infra-meta",
        json={"env": {"CUSTOM_PLATFORM_VAR": "keep", "OPIK_URL": "http://old/api"}},
        headers=_csrf_headers(),
    )
    resp = await client.put(
        "/api/infra-meta",
        json={"env": {"OPIK_URL": "http://new/api"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["env"] == {
        "CUSTOM_PLATFORM_VAR": "keep",
        "OPIK_URL": "http://new/api",
    }


async def test_upsert_infra_meta_secrets(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"secrets": {"OPENAI_API_KEY": "sk-test"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert "OPENAI_API_KEY" in resp.json()["secret_keys"]


async def test_upsert_infra_meta_custom_secret(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"secrets": {"MY_VENDOR_API_KEY": "secret-value"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert "MY_VENDOR_API_KEY" in resp.json()["secret_keys"]


async def test_upsert_infra_meta_rejects_unknown_secret(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"secrets": {"pod_name": "x"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 400


async def test_upsert_infra_meta_requires_body(client: AsyncClient):
    resp = await client.put("/api/infra-meta", json={}, headers=_csrf_headers())
    assert resp.status_code == 400


async def test_upsert_infra_meta_rejects_invalid_env(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"env": {"opik_url": "value"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 400


async def test_upsert_infra_meta_accepts_custom_env(client: AsyncClient):
    resp = await client.put(
        "/api/infra-meta",
        json={"env": {"MY_PLATFORM_FLAG": "enabled"}},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["env"]["MY_PLATFORM_FLAG"] == "enabled"


async def test_get_infra_meta_after_upsert(client: AsyncClient):
    await client.put(
        "/api/infra-meta",
        json={"env": {"DEFAULT_LLM_MODEL": "openai:gpt-4o-mini"}},
        headers=_csrf_headers(),
    )
    resp = await client.get("/api/infra-meta", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["env"]["DEFAULT_LLM_MODEL"] == "openai:gpt-4o-mini"


# ---------------------------------------------------------------------------
# llm_presets
# ---------------------------------------------------------------------------


async def test_llm_presets_crud(client: AsyncClient):
    # 1. List presets initially empty
    resp = await client.get("/api/llm-presets", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json() == []

    # 2. Create preset
    resp = await client.post(
        "/api/llm-presets",
        json={
            "name": "CLAUDE_TEST",
            "description": "My test preset",
            "mode": "frontier",
            "frontier_provider": "anthropic",
            "model_id": "claude-3-5-sonnet",
            "is_default": True,
            "api_key": "sk-ant-test-key",
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "CLAUDE_TEST"
    assert data["is_default"] is True
    assert data["api_key_configured"] is True
    preset_id = data["id"]

    # 3. Retrieve preset
    resp = await client.get(f"/api/llm-presets/{preset_id}", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json()["name"] == "CLAUDE_TEST"

    # 4. Duplicate name should fail
    resp = await client.post(
        "/api/llm-presets",
        json={
            "name": "CLAUDE_TEST",
            "mode": "frontier",
            "model_id": "claude-other",
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 409

    # 5. Invalid name pattern should fail (Pydantic validation -> 422)
    resp = await client.post(
        "/api/llm-presets",
        json={
            "name": "claude-test",
            "mode": "frontier",
            "model_id": "claude-other",
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 422

    # 6. Update preset
    resp = await client.put(
        f"/api/llm-presets/{preset_id}",
        json={
            "description": "Updated desc",
            "mode": "frontier",
            "frontier_provider": "anthropic",
            "model_id": "claude-3-5-opus",
            "is_default": False,
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["model_id"] == "claude-3-5-opus"
    assert resp.json()["is_default"] is False

    # 7. Delete preset
    resp = await client.delete(f"/api/llm-presets/{preset_id}", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    # 8. List empty again
    resp = await client.get("/api/llm-presets", headers=_csrf_headers())
    assert resp.status_code == 200
    assert resp.json() == []



# ---------------------------------------------------------------------------
# Bundle upload / download
# ---------------------------------------------------------------------------


def _make_zip_bytes() -> bytes:
    """Create a minimal valid zip file in memory."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "def build_graph(cfg, secrets): pass\n")
    return buf.getvalue()


async def test_upload_bundle_201(client: AsyncClient):
    """POST /api/source-meta/bundle uploads a zip and creates source_meta."""
    import io
    import json

    meta = {
        "kind": "agent",
        "name": "upload-agent",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "main:build_graph",
    }
    zip_bytes = _make_zip_bytes()
    resp = await client.post(
        "/api/source-meta/bundle",
        files={
            "file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip"),
        },
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "upload-agent"
    assert data["checksum"].startswith("sha256:")
    assert data["bundle_uri"].endswith(".zip")


async def test_upload_bundle_duplicate_409(client: AsyncClient):
    """Uploading same (kind, name, version) twice returns 409."""
    import io
    import json

    meta = {
        "kind": "agent",
        "name": "dup-upload-agent",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "main:build_graph",
    }
    zip_bytes = _make_zip_bytes()

    def _files():
        return {"file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip")}

    await client.post(
        "/api/source-meta/bundle",
        files=_files(),
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    resp = await client.post(
        "/api/source-meta/bundle",
        files=_files(),
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 409


async def test_serve_bundle_200(client: AsyncClient):
    """GET /bundles/{sha256}.zip serves the uploaded bundle."""
    import io
    import json

    meta = {
        "kind": "agent",
        "name": "serve-agent",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "main:build_graph",
    }
    zip_bytes = _make_zip_bytes()
    upload = await client.post(
        "/api/source-meta/bundle",
        files={"file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip")},
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    assert upload.status_code == 201
    checksum = upload.json()["checksum"]  # "sha256:<hex>"
    sha256_hex = checksum.removeprefix("sha256:")
    resp = await client.get(f"/bundles/{sha256_hex}.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"


async def test_serve_bundle_not_found_404(client: AsyncClient):
    bad_sha = "a" * 64
    resp = await client.get(f"/bundles/{bad_sha}.zip")
    assert resp.status_code == 404


async def test_serve_bundle_invalid_sha_404(client: AsyncClient):
    resp = await client.get("/bundles/not-a-hash.zip")
    assert resp.status_code == 404


async def test_serve_bundle_blocked_when_forwarded(client: AsyncClient):
    """Requests via Ingress/proxy (X-Forwarded-*) must not download bundles."""
    import io
    import json

    meta = {
        "kind": "agent",
        "name": "fwd-block-agent",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "main:build_graph",
    }
    zip_bytes = _make_zip_bytes()
    upload = await client.post(
        "/api/source-meta/bundle",
        files={"file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip")},
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    assert upload.status_code == 201
    sha256_hex = upload.json()["checksum"].removeprefix("sha256:")

    resp = await client.get(
        f"/bundles/{sha256_hex}.zip",
        headers={"X-Forwarded-For": "203.0.113.1"},
    )
    assert resp.status_code == 403


async def test_serve_bundle_allowed_without_forwarded_headers(client: AsyncClient):
    """In-cluster pool fetches (no proxy headers) still receive the bundle redirect."""
    import io
    import json

    meta = {
        "kind": "agent",
        "name": "direct-bundle-agent",
        "version": "v1",
        "runtime_pool": "agent:compiled_graph",
        "entrypoint": "main:build_graph",
    }
    zip_bytes = _make_zip_bytes()
    upload = await client.post(
        "/api/source-meta/bundle",
        files={"file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip")},
        data={"meta": json.dumps(meta)},
        headers=_csrf_headers(),
    )
    assert upload.status_code == 201
    sha256_hex = upload.json()["checksum"].removeprefix("sha256:")

    resp = await client.get(f"/bundles/{sha256_hex}.zip", follow_redirects=False)
    assert resp.status_code in {200, 307}


# ---------------------------------------------------------------------------
# S3BundleStorage URI generation
# ---------------------------------------------------------------------------


def test_s3_bundle_uri_uses_base_url():
    """bundle_uri must be HTTP so pool pod loader can fetch via presigned redirect."""
    from backend.bundle_storage import S3BundleStorage

    storage = S3BundleStorage(
        bucket="agent-bundles",
        prefix="bundles/",
        endpoint_url="https://kr.object.ncloudstorage.com",
        region="kr-standard",
        access_key=None,
        secret_key=None,
        presign_expiry=3600,
        base_url="http://backend:8000/bundles",
    )
    sha = "a" * 64
    assert storage._bundle_uri(sha) == f"http://backend:8000/bundles/{sha}.zip"
    assert storage._sig_uri(sha) == f"http://backend:8000/bundles/{sha}.sig"
    assert not storage._bundle_uri(sha).startswith("s3://")


def test_s3_bundle_uri_fallback_without_base_url():
    """Without base_url, falls back to relative path (not s3://)."""
    from backend.bundle_storage import S3BundleStorage

    storage = S3BundleStorage(
        bucket="agent-bundles",
        prefix="bundles/",
        endpoint_url=None,
        region="us-east-1",
        access_key=None,
        secret_key=None,
        presign_expiry=3600,
    )
    sha = "b" * 64
    assert storage._bundle_uri(sha) == f"/bundles/{sha}.zip"
    assert not storage._bundle_uri(sha).startswith("s3://")


async def test_s3_ensure_ready_retries_until_bucket_available(monkeypatch):
    """Garage may start slightly after backend; S3 startup should retry head_bucket."""
    import asyncio

    from backend.bundle_storage import S3BundleStorage

    storage = S3BundleStorage(
        bucket="runtime-bundles",
        prefix="bundles/",
        endpoint_url="http://garage-s3.runtime.svc.cluster.local:3900",
        region="garage",
        access_key="GKdev",
        secret_key="secret",
        presign_expiry=3600,
        base_url="http://backend.runtime.svc.cluster.local:8000/bundles",
    )

    attempts = {"count": 0}

    class _FakeS3:
        async def head_bucket(self, *, Bucket: str) -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("connection refused")
            assert Bucket == "runtime-bundles"

    class _FakeClient:
        async def __aenter__(self) -> _FakeS3:
            return _FakeS3()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _FakeSession:
        def client(self, _service: str, **_kwargs: object) -> _FakeClient:
            return _FakeClient()

    async def _noop_sleep(_sec: float) -> None:
        return None

    monkeypatch.setattr("aioboto3.Session", lambda: _FakeSession())
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    await storage.ensure_ready(max_attempts=5, retry_delay_sec=0)

    assert attempts["count"] == 3


# ---------------------------------------------------------------------------
# Signature upload
# ---------------------------------------------------------------------------


async def test_upload_signature(client: AsyncClient):
    """POST /api/source-meta/{id}/signature attaches a sig and returns sig_uri."""
    import io
    import json

    from backend.app import app

    # Use a distinct access_token so both the bundle upload and the signature POST
    # get their own upload rate-limit bucket, independent of other bundle tests.
    sig_token = "sig-test-token"
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": sig_token, _csrf_cookie_name(): _CSRF},
    ) as sig_client:
        meta = {
            "kind": "agent",
            "name": "sig-agent",
            "version": "v1",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": "main:build_graph",
        }
        zip_bytes = _make_zip_bytes()
        create = await sig_client.post(
            "/api/source-meta/bundle",
            files={"file": ("bundle.zip", io.BytesIO(zip_bytes), "application/zip")},
            data={"meta": json.dumps(meta)},
            headers=_csrf_headers(),
        )
        assert create.status_code == 201
        sm_id = create.json()["id"]

        sig_bytes = b"fake-signature-data"
        resp = await sig_client.post(
            f"/api/source-meta/{sm_id}/signature",
            files={"sig": ("bundle.sig", io.BytesIO(sig_bytes), "application/octet-stream")},
            headers=_csrf_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["sig_uri"] is not None

    # Verify the record is also visible through the fixture client
    get_resp = await client.get(f"/api/source-meta/{sm_id}", headers=_csrf_headers())
    assert get_resp.status_code == 200
    assert get_resp.json()["sig_uri"] is not None


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


async def test_get_audit_log(client: AsyncClient):
    """GET /api/audit returns log entries (admin only)."""
    # Creating a source_meta generates an audit entry
    await client.post("/api/source-meta", json=_VALID_SOURCE_BODY, headers=_csrf_headers())
    resp = await client.get("/api/audit", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    # At least the create event above should be recorded
    assert data["total"] >= 1


async def test_get_audit_log_filter_action(client: AsyncClient):
    """GET /api/audit?action=source_meta filters by prefix correctly."""
    await client.post(
        "/api/source-meta",
        json={**_VALID_SOURCE_BODY, "name": "audit-filter-bot", "version": "v99"},
        headers=_csrf_headers(),
    )
    resp = await client.get("/api/audit", params={"action": "source_meta"}, headers=_csrf_headers())
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all("source_meta" in item["action"] for item in items)


async def test_get_audit_log_pagination(client: AsyncClient):
    """GET /api/audit honors limit/offset and returns stable disjoint pages."""
    for i in range(5):
        await client.post(
            "/api/source-meta",
            json={**_VALID_SOURCE_BODY, "name": f"audit-pag-bot-{i}", "version": f"v{i}"},
            headers=_csrf_headers(),
        )
    page1 = await client.get(
        "/api/audit",
        params={"limit": 2, "offset": 0},
        headers=_csrf_headers(),
    )
    page2 = await client.get(
        "/api/audit",
        params={"limit": 2, "offset": 2},
        headers=_csrf_headers(),
    )
    assert page1.status_code == 200
    assert page2.status_code == 200
    data1 = page1.json()
    data2 = page2.json()
    assert data1["total"] >= 5
    assert len(data1["items"]) == 2
    assert len(data2["items"]) == 2
    ids1 = {item["id"] for item in data1["items"]}
    ids2 = {item["id"] for item in data2["items"]}
    assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


async def test_get_me(client: AsyncClient):
    """GET /api/me returns current user info when user exists in DB."""
    from backend.app import app

    # The mock auth returns user_id=1; insert a user so id=1 exists.
    # SQLite auto-increments from 1 on first insert.
    user = await _insert_user(app.state, "me-user", role="admin")
    # user.id should be 1 if the table is empty, but may differ in shared state.
    # Patch the mock to return the actual user id so /api/me can find it.
    from unittest.mock import AsyncMock

    from runtime_common.schemas import Principal

    principal_data = {**_ADMIN_PRINCIPAL, "user_id": user.id}
    app.state.auth_client.verify = AsyncMock(return_value=Principal.model_validate(principal_data))

    resp = await client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user.id
    assert data["username"] == "me-user"


async def test_get_access_token(client: AsyncClient):
    """GET /api/auth/access-token returns Bearer JWT from the session cookie."""
    resp = await client.get("/api/auth/access-token")
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "valid-token"

# ---------------------------------------------------------------------------
# Bulk access grant / revoke
# ---------------------------------------------------------------------------


async def test_bulk_access_grant_and_revoke(client: AsyncClient):
    """POST /api/users/{id}/access:bulk grants and revokes in separate calls."""
    from backend.app import app

    source1 = await _insert_source(
        app.state, {"name": "bulk-src-1", "checksum": "sha256:" + "1" * 64}
    )
    source2 = await _insert_source(
        app.state, {"name": "bulk-src-2", "checksum": "sha256:" + "2" * 64}
    )
    user = await _insert_user(app.state, "bulk-user")

    # Grant both
    resp = await client.post(
        f"/api/users/{user.id}/access:bulk",
        json={
            "action": "grant",
            "items": [
                {"kind": source1.kind, "name": source1.name},
                {"kind": source2.kind, "name": source2.name},
            ],
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 204

    # Verify both granted
    check = await client.get(f"/api/users/{user.id}/access", headers=_csrf_headers())
    names = [i["name"] for i in check.json()["items"]]
    assert source1.name in names
    assert source2.name in names

    # Now revoke source1
    resp2 = await client.post(
        f"/api/users/{user.id}/access:bulk",
        json={
            "action": "revoke",
            "items": [{"kind": source1.kind, "name": source1.name}],
        },
        headers=_csrf_headers(),
    )
    assert resp2.status_code == 204

    check2 = await client.get(f"/api/users/{user.id}/access", headers=_csrf_headers())
    names2 = [i["name"] for i in check2.json()["items"]]
    assert source1.name not in names2
    assert source2.name in names2


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


async def test_admin_force_password_change(client: AsyncClient):
    """POST /api/users/{id}/password allows admin to set new password."""
    from backend.app import app

    user = await _insert_user(app.state, "pwd-change-user")
    resp = await client.post(
        f"/api/users/{user.id}/password",
        json={"password": "NewStrongPass123!"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 204


async def test_admin_force_password_change_weak_400(client: AsyncClient):
    """POST /api/users/{id}/password rejects weak passwords with 400."""
    from backend.app import app

    user = await _insert_user(app.state, "weak-pwd-user")
    resp = await client.post(
        f"/api/users/{user.id}/password",
        json={"password": "weak"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


async def test_dashboard_summary_accessible_to_authenticated_user(client: AsyncClient):
    from unittest.mock import AsyncMock

    from backend.app import app
    from runtime_common.schemas import Principal

    user_principal = Principal.model_validate(
        {
            "sub": "alice",
            "user_id": 2,
            "tenant": "dev",
            "access": [],
            "grace_applied": False,
            "role": "user",
            "must_change_password": False,
        }
    )
    app.state.auth_client.verify = AsyncMock(return_value=user_principal)

    resp = await client.get("/api/dashboard/summary", headers=_csrf_headers())
    assert resp.status_code == 200


async def test_dashboard_summary_resource_counts(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state, {"name": "active-agent", "status": "active"})
    await _insert_source(
        app.state,
        {
            "name": "pending-agent",
            "checksum": "sha256:" + "d" * 64,
            "status": "pending",
        },
    )
    await _insert_source(
        app.state,
        {
            "kind": "mcp",
            "name": "failed-mcp",
            "runtime_pool": "mcp:fastmcp",
            "checksum": "sha256:" + "e" * 64,
            "status": "failed",
        },
    )
    await _insert_source(
        app.state,
        {
            "name": "retired-agent",
            "checksum": "sha256:" + "f" * 64,
            "retired": True,
        },
    )

    resp = await client.get("/api/dashboard/summary", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()

    assert data["resources"]["agent"]["total"] == 3
    assert data["resources"]["agent"]["active"] == 1
    assert data["resources"]["agent"]["pending"] == 1
    assert data["resources"]["agent"]["retired"] == 1
    assert data["resources"]["mcp"]["total"] == 1
    assert data["resources"]["mcp"]["failed"] == 1

    assert len(data["recent_issues"]) == 2
    issue_names = {item["name"] for item in data["recent_issues"]}
    assert issue_names == {"pending-agent", "failed-mcp"}

    assert data["pools"]["available"] is False
    assert data["pools"]["error"] == "REDIS_URL not configured"


# ---------------------------------------------------------------------------
# General agent tier (POST /api/source-meta/general)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_general_agent_201(client: AsyncClient):
    from backend.app import app
    from backend.deps import get_settings
    from runtime_common.schemas import Principal

    settings = get_settings()

    respx.get(f"{settings.ENVOY_URL}/v1/mcp/servers/search-server/catalog").mock(
        return_value=Response(
            200,
            json={
                "tools": [
                    {"name": "naver_search", "description": "Search"},
                    {"name": "fetch_url", "description": "Fetch"},
                ]
            },
        )
    )

    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = Principal.model_validate(
        {**_ADMIN_PRINCIPAL, "access": [{"kind": "mcp", "name": "search-server"}]}
    )
    try:
        resp = await client.post(
            "/api/source-meta/general",
            headers=_csrf_headers(),
            json={
                "name": "research-bot",
                "version": "v1",
                "system_prompt": "You are a researcher.",
                "mcp_servers": ["search-server"],
                "config": {"langgraph": {"model": "anthropic:claude-sonnet-4-6"}},
            },
        )
    finally:
        app.state.auth_client.verify.return_value = prev

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["deploy_mode"] == "general"
    assert data["runtime_pool"] == "agent:compiled_graph"
    assert data["entrypoint"] is None
    assert data["bundle_uri"] is None
    assert data["config"]["general"]["system_prompt"] == "You are a researcher."
    assert len(data["config"]["general"]["mcp_tools"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_create_general_agent_duplicate_409(client: AsyncClient):
    from backend.app import app
    from backend.deps import get_settings
    from runtime_common.schemas import Principal

    settings = get_settings()

    respx.get(f"{settings.ENVOY_URL}/v1/mcp/servers/s/catalog").mock(
        return_value=Response(200, json={"tools": [{"name": "t", "description": ""}]})
    )
    payload = {
        "name": "dup-bot",
        "version": "v1",
        "system_prompt": "Hi",
        "mcp_servers": ["s"],
    }
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = Principal.model_validate(
        {**_ADMIN_PRINCIPAL, "access": [{"kind": "mcp", "name": "s"}]}
    )
    try:
        r1 = await client.post("/api/source-meta/general", headers=_csrf_headers(), json=payload)
        assert r1.status_code == 201
        r2 = await client.post("/api/source-meta/general", headers=_csrf_headers(), json=payload)
        assert r2.status_code == 409
    finally:
        app.state.auth_client.verify.return_value = prev


@pytest.mark.asyncio
async def test_create_general_agent_no_mcp_access_403(client: AsyncClient):
    resp = await client.post(
        "/api/source-meta/general",
        headers=_csrf_headers(),
        json={
            "name": "research-bot",
            "version": "v1",
            "system_prompt": "You are a researcher.",
            "mcp_servers": ["search-server"],
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# General agent visibility
# ---------------------------------------------------------------------------


def _general_agent_config():
    return {
        "general": {
            "system_prompt": "Hi",
            "mcp_servers": ["s"],
            "mcp_tools": [{"server": "s", "name": "t", "description": ""}],
        }
    }


async def _set_test_principal(principal: dict) -> None:
    from backend.app import app
    from runtime_common.schemas import Principal

    app.state.auth_client.verify.return_value = Principal.model_validate(principal)


@pytest.mark.asyncio
@respx.mock
async def test_create_general_agent_sets_visibility_and_owner(client: AsyncClient):
    from backend.app import app
    from backend.deps import get_settings

    settings = get_settings()
    respx.get(f"{settings.ENVOY_URL}/v1/mcp/servers/s/catalog").mock(
        return_value=Response(200, json={"tools": [{"name": "t", "description": ""}]})
    )

    owner = await _insert_user(app.state, "owner-user", tenant="acme")
    await _set_test_principal(
        {
            **_ADMIN_PRINCIPAL,
            "user_id": owner.id,
            "sub": owner.username,
            "tenant": "acme",
            "role": "user",
            "access": [{"kind": "mcp", "name": "s"}],
        },
    )

    resp = await client.post(
        "/api/source-meta/general",
        headers=_csrf_headers(),
        json={
            "name": "team-bot",
            "version": "v1",
            "system_prompt": "Hello",
            "mcp_servers": ["s"],
            "visibility": "tenant",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["visibility"] == "tenant"
    assert data["created_by_user_id"] == owner.id
    assert data["owner_tenant"] == "acme"


@pytest.mark.asyncio
async def test_list_general_agents_respects_visibility(client: AsyncClient):
    from backend.app import app

    owner = await _insert_user(app.state, "owner-a", tenant="acme")
    other = await _insert_user(app.state, "other-b", tenant="beta")

    await _insert_source(
        app.state,
        {
            "name": "private-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": "acme",
            "visibility": "private",
        },
    )
    await _insert_source(
        app.state,
        {
            "name": "tenant-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": "acme",
            "visibility": "tenant",
        },
    )
    await _insert_source(
        app.state,
        {
            "name": "public-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": "acme",
            "visibility": "public",
        },
    )

    await _set_test_principal(
        {
            **_ADMIN_PRINCIPAL,
            "user_id": other.id,
            "sub": other.username,
            "tenant": "beta",
            "role": "user",
            "access": [],
        },
    )

    resp = await client.get(
        "/api/source-meta",
        params={"kind": "agent", "deploy_mode": "general"},
    )
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["items"]}
    assert names == {"public-bot"}


@pytest.mark.asyncio
async def test_get_private_general_agent_denies_non_owner(client: AsyncClient):
    from backend.app import app

    owner = await _insert_user(app.state, "owner-c", tenant="acme")
    stranger = await _insert_user(app.state, "stranger-d", tenant="acme")
    row = await _insert_source(
        app.state,
        {
            "name": "secret-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": "acme",
            "visibility": "private",
        },
    )

    await _set_test_principal(
        {
            **_ADMIN_PRINCIPAL,
            "user_id": stranger.id,
            "sub": stranger.username,
            "tenant": "acme",
            "role": "user",
            "access": [],
        },
    )

    resp = await client.get(f"/api/source-meta/{row.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_general_visibility_by_creator(client: AsyncClient):
    from backend.app import app

    owner = await _insert_user(app.state, "owner-e", tenant="acme")
    row = await _insert_source(
        app.state,
        {
            "name": "patch-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": "acme",
            "visibility": "private",
        },
    )

    await _set_test_principal(
        {
            **_ADMIN_PRINCIPAL,
            "user_id": owner.id,
            "sub": owner.username,
            "tenant": "acme",
            "role": "user",
            "access": [{"kind": "mcp", "name": "s"}],
        },
    )

    resp = await client.patch(
        f"/api/source-meta/general/{row.id}",
        headers=_csrf_headers(),
        json={"visibility": "public"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visibility"] == "public"


@pytest.mark.asyncio
async def test_patch_general_tenant_visibility_uses_db_tenant(client: AsyncClient):
    """JWT may omit tenant while users.tenant is set (stale token)."""
    from backend.app import app

    owner = await _insert_user(app.state, "tenant-owner", tenant="acme")
    row = await _insert_source(
        app.state,
        {
            "name": "stale-token-bot",
            "deploy_mode": "general",
            "runtime_pool": "agent:compiled_graph",
            "entrypoint": None,
            "bundle_uri": None,
            "checksum": None,
            "config": _general_agent_config(),
            "created_by_user_id": owner.id,
            "owner_tenant": None,
            "visibility": "private",
        },
    )

    await _set_test_principal(
        {
            **_ADMIN_PRINCIPAL,
            "user_id": owner.id,
            "sub": owner.username,
            "tenant": None,
            "role": "user",
            "access": [{"kind": "mcp", "name": "s"}],
        },
    )

    resp = await client.patch(
        f"/api/source-meta/general/{row.id}",
        headers=_csrf_headers(),
        json={"visibility": "tenant"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["visibility"] == "tenant"
    assert data["owner_tenant"] == "acme"


@pytest.mark.asyncio
async def test_me_access_resources_chat_surface_filters_non_selectable(client: AsyncClient):
    from backend.app import app

    await _insert_source(
        app.state,
        {
            "kind": "agent",
            "name": "chat-visible",
            "chat_selectable": True,
        },
    )
    await _insert_source(
        app.state,
        {
            "kind": "agent",
            "name": "delegate-only",
            "chat_selectable": False,
        },
    )
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "bob",
        [
            {"kind": "agent", "name": "chat-visible"},
            {"kind": "agent", "name": "delegate-only"},
        ],
    )
    try:
        all_resp = await client.get(
            "/api/me/access-resources",
            params={"kind": "agent"},
            headers=_csrf_headers(),
        )
        assert all_resp.status_code == 200
        assert {i["name"] for i in all_resp.json()["items"]} == {
            "chat-visible",
            "delegate-only",
        }

        chat_resp = await client.get(
            "/api/me/access-resources",
            params={"kind": "agent", "surface": "chat"},
            headers=_csrf_headers(),
        )
        assert chat_resp.status_code == 200
        names = {i["name"] for i in chat_resp.json()["items"]}
        assert names == {"chat-visible"}
    finally:
        app.state.auth_client.verify.return_value = prev


@pytest.mark.asyncio
async def test_create_general_agent_rejects_delegate_without_access(client: AsyncClient):
    from backend.app import app

    await _insert_source(app.state, {"kind": "mcp", "name": "search-server"})
    prev = app.state.auth_client.verify.return_value
    app.state.auth_client.verify.return_value = _user_principal(
        "bob",
        [{"kind": "mcp", "name": "search-server"}],
    )
    try:
        resp = await client.post(
            "/api/source-meta/general",
            headers=_csrf_headers(),
            json={
                "name": "orchestrator",
                "version": "v1",
                "system_prompt": "You coordinate tasks.",
                "mcp_servers": ["search-server"],
                "delegate_agents": ["missing-agent"],
            },
        )
        assert resp.status_code == 403
        assert "missing-agent" in resp.json()["detail"]
    finally:
        app.state.auth_client.verify.return_value = prev
