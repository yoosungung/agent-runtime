"""Tests for custom image mode: slug derivation, config size limit, CRUD API."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base

TEST_DSN = "sqlite+aiosqlite:///:memory:"

_ADMIN_PRINCIPAL = {
    "sub": "admin",
    "user_id": 1,
    "tenant": None,
    "access": [],
    "grace_applied": False,
    "is_admin": True,
    "must_change_password": False,
}
_CSRF = "test-csrf"


def _make_test_settings(**overrides):
    import backend.settings as _settings_mod

    defaults = dict(
        POSTGRES_DSN=TEST_DSN,
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR="/tmp/backend-test-bundles-ci",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
        K8S_IN_CLUSTER=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture()
async def client(monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from backend.bundle_storage import LocalBundleStorage
    from unittest.mock import AsyncMock
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
    admin_principal = Principal.model_validate(_ADMIN_PRINCIPAL)
    mock_auth.verify = AsyncMock(return_value=admin_principal)
    mock_auth.revoke_tokens = AsyncMock(return_value=None)
    mock_auth.refresh = AsyncMock(return_value={"access_token": "new", "refresh_token": "new"})
    mock_auth.logout = AsyncMock(return_value=None)
    mock_auth._client = AsyncMock()
    mock_auth._client.post = AsyncMock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    app.state.auth_client = mock_auth
    # No K8s pool manager in tests — endpoints skip K8s and mark active immediately
    app.state.k8s_pool_manager = None

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "valid-token", "csrf_token": _CSRF},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


def _headers() -> dict[str, str]:
    return {"X-CSRF-Token": _CSRF}


# ---------------------------------------------------------------------------
# Slug derivation helper
# ---------------------------------------------------------------------------


def test_derive_slug_basic():
    from backend.routers.custom_images import _derive_slug

    assert _derive_slug("Summarizer Agent", "v2.0") == "summarizer-agent-v2-0"


def test_derive_slug_truncates():
    from backend.routers.custom_images import _derive_slug

    slug = _derive_slug("a" * 30, "b" * 30)
    assert len(slug) <= 45


def test_derive_slug_no_leading_trailing_hyphens():
    from backend.routers.custom_images import _derive_slug

    slug = _derive_slug("---test---", "---v1---")
    assert slug[0].isalnum()
    assert slug[-1].isalnum()


# ---------------------------------------------------------------------------
# Config size validation
# ---------------------------------------------------------------------------


def test_validate_config_within_limit():
    from backend.routers.custom_images import _validate_config

    _validate_config({"key": "value"})  # no exception


def test_validate_config_exceeds_16kb():
    from fastapi import HTTPException
    from backend.routers.custom_images import _validate_config

    big_config = {"data": "x" * (16 * 1024 + 1)}
    with pytest.raises(HTTPException) as exc_info:
        _validate_config(big_config)
    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# POST /api/admin/custom-images
# ---------------------------------------------------------------------------


async def test_create_custom_image(client: AsyncClient):
    r = await client.post(
        "/api/admin/custom-images",
        json={
            "kind": "agent",
            "name": "summarizer-agent",
            "version": "v1.0",
            "image_uri": "registry.example.com/summarizer-agent:v1.0",
            "replicas_max": 3,
        },
        headers=_headers(),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["deploy_mode"] == "image"
    assert data["status"] == "active"  # K8s skipped → immediate active
    assert data["slug"] is not None
    assert data["runtime_pool"].startswith("agent:custom:")


async def test_create_custom_image_explicit_slug(client: AsyncClient):
    r = await client.post(
        "/api/admin/custom-images",
        json={
            "kind": "mcp",
            "name": "my-mcp",
            "version": "v2",
            "image_uri": "registry.example.com/my-mcp:v2",
            "slug": "my-mcp-v2",
        },
        headers=_headers(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "my-mcp-v2"
    assert r.json()["runtime_pool"] == "mcp:custom:my-mcp-v2"


async def test_create_duplicate_slug_409(client: AsyncClient):
    payload = {
        "kind": "agent",
        "name": "agent-a",
        "version": "v1",
        "image_uri": "reg/agent-a:v1",
        "slug": "unique-slug-x1",
    }
    r1 = await client.post("/api/admin/custom-images", json=payload, headers=_headers())
    assert r1.status_code == 201, r1.text

    payload2 = {**payload, "name": "agent-b", "version": "v2"}
    r2 = await client.post("/api/admin/custom-images", json=payload2, headers=_headers())
    assert r2.status_code == 409


async def test_create_invalid_kind_400(client: AsyncClient):
    r = await client.post(
        "/api/admin/custom-images",
        json={"kind": "unknown", "name": "x", "version": "v1", "image_uri": "r/x:v1"},
        headers=_headers(),
    )
    assert r.status_code == 400


async def test_create_invalid_slug_400(client: AsyncClient):
    r = await client.post(
        "/api/admin/custom-images",
        json={
            "kind": "agent",
            "name": "x",
            "version": "v1",
            "image_uri": "r/x:v1",
            "slug": "INVALID_SLUG",
        },
        headers=_headers(),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/admin/custom-images
# ---------------------------------------------------------------------------


async def test_list_custom_images(client: AsyncClient):
    # Create two images
    for i in range(2):
        await client.post(
            "/api/admin/custom-images",
            json={
                "kind": "agent",
                "name": f"agent-list-{i}",
                "version": "v1",
                "image_uri": f"reg/agent-{i}:v1",
            },
            headers=_headers(),
        )

    r = await client.get("/api/admin/custom-images?kind=agent", headers=_headers())
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 2
    assert all(item["deploy_mode"] == "image" for item in items)


# ---------------------------------------------------------------------------
# DELETE /api/admin/custom-images/{kind}/{slug}
# ---------------------------------------------------------------------------


async def test_delete_custom_image(client: AsyncClient):
    create_r = await client.post(
        "/api/admin/custom-images",
        json={
            "kind": "agent",
            "name": "to-delete",
            "version": "v1",
            "image_uri": "reg/to-delete:v1",
            "slug": "to-delete-v1",
        },
        headers=_headers(),
    )
    assert create_r.status_code == 201

    del_r = await client.delete(
        "/api/admin/custom-images/agent/to-delete-v1", headers=_headers()
    )
    assert del_r.status_code == 204

    # Verify it's retired in the list (retired images still appear in list)
    list_r = await client.get("/api/admin/custom-images?kind=agent", headers=_headers())
    retired = [item for item in list_r.json() if item["slug"] == "to-delete-v1"]
    if retired:
        assert retired[0]["status"] == "retired"


async def test_delete_nonexistent_404(client: AsyncClient):
    r = await client.delete(
        "/api/admin/custom-images/agent/no-such-slug", headers=_headers()
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/admin/custom-images/{kind}/{slug}
# ---------------------------------------------------------------------------


async def test_patch_custom_image_config(client: AsyncClient):
    create_r = await client.post(
        "/api/admin/custom-images",
        json={
            "kind": "agent",
            "name": "patch-test",
            "version": "v1",
            "image_uri": "reg/patch-test:v1",
            "slug": "patch-test-v1",
            "config": {"model": "claude-3"},
        },
        headers=_headers(),
    )
    assert create_r.status_code == 201

    patch_r = await client.patch(
        "/api/admin/custom-images/agent/patch-test-v1",
        json={"config": {"model": "claude-4"}},
        headers=_headers(),
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["config"]["model"] == "claude-4"


async def test_patch_nonexistent_404(client: AsyncClient):
    r = await client.patch(
        "/api/admin/custom-images/agent/no-such-slug",
        json={"config": {}},
        headers=_headers(),
    )
    assert r.status_code == 404


