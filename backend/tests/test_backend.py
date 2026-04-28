"""Integration tests for the admin-console backend (FastAPI BFF).

Uses SQLite in-memory via aiosqlite so no Postgres is needed.
Auth service calls are intercepted with respx.
CSRF validation is bypassed via monkeypatching validate_csrf.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# runtime_common.db.models is already patched by conftest.py
from runtime_common.db.models import Base, SourceMetaRow, UserRow

TEST_DSN = "sqlite+aiosqlite:///:memory:"

# Admin principal JSON returned by the mock auth /verify endpoint
_ADMIN_PRINCIPAL = {
    "sub": "admin",
    "user_id": 1,
    "tenant": None,
    "access": [],
    "grace_applied": False,
    "is_admin": True,
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


async def _insert_user(app_state, username: str = "alice", is_admin: bool = False) -> UserRow:
    from backend.app import app
    from backend.passwords import hash_password

    async with app.state.session_factory() as session:
        row = UserRow(
            username=username,
            password_hash=hash_password("TestPass123!"),
            tenant=None,
            disabled=False,
            is_admin=is_admin,
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
            "is_admin": False,
        },
        headers=_csrf_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "bob"
    assert data["is_admin"] is False


async def test_create_user_weak_password_400(client: AsyncClient):
    resp = await client.post(
        "/api/users",
        json={"username": "carol", "password": "short"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 400


async def test_create_user_duplicate_409(client: AsyncClient):
    body = {"username": "dave", "password": "StrongPassword123!", "is_admin": False}
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
    await _insert_user(app.state, "placeholder-admin", is_admin=True)
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


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


async def test_get_me(client: AsyncClient):
    """GET /api/me returns current user info when user exists in DB."""
    from backend.app import app

    # The mock auth returns user_id=1; insert a user so id=1 exists.
    # SQLite auto-increments from 1 on first insert.
    user = await _insert_user(app.state, "me-user", is_admin=True)
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
