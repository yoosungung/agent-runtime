from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base

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
        BUNDLE_STORAGE_DIR="/tmp/bucket-router-test",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


@pytest_asyncio.fixture
async def bucket_client(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    import backend.deps as _deps_mod
    from backend.app import app
    from backend.bundle_storage import LocalBundleStorage
    from backend.object_store_browser import LocalObjectStoreBrowser
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    storage_dir = tmp_path / "bundles"
    storage_dir.mkdir()
    (storage_dir / "tmp").mkdir()

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

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_ADMIN_PRINCIPAL))
    app.state.auth_client = mock_auth

    from backend.pool_status import PoolRegistryMonitor

    app.state.pool_monitor = PoolRegistryMonitor("")

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
async def test_bucket_info(bucket_client: AsyncClient):
    resp = await bucket_client.get("/api/bucket/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "local"
    assert "bundles" in body["root_label"]


@pytest.mark.asyncio
async def test_bucket_create_list_delete(bucket_client: AsyncClient):
    resp = await bucket_client.post(
        "/api/bucket/folders",
        json={"parent_prefix": "", "name": "imports"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 201

    resp = await bucket_client.get("/api/bucket/objects")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert "imports" in names
    assert "tmp" not in names

    resp = await bucket_client.request(
        "DELETE",
        "/api/bucket/objects",
        json={"keys": ["imports/"]},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_bucket_delete_referenced_bundle_returns_409(bucket_client: AsyncClient, tmp_path):
    hex64 = "b" * 64
    bundle_path = tmp_path / "bundles" / f"{hex64}.zip"
    bundle_path.write_bytes(b"zip")

    from backend.app import app
    from runtime_common.db.models import SourceMetaRow

    async with app.state.session_factory() as session:
        row = SourceMetaRow(
            kind="agent",
            name="bot",
            version="v1",
            runtime_pool="agent:compiled_graph",
            entrypoint="app:build_graph",
            bundle_uri=f"/bundles/{hex64}.zip",
            checksum=f"sha256:{hex64}",
            config={},
            retired=False,
        )
        session.add(row)
        await session.commit()

    resp = await bucket_client.request(
        "DELETE",
        "/api/bucket/objects",
        json={"keys": [f"{hex64}.zip"]},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_bucket_move_file(bucket_client: AsyncClient, tmp_path):
    hex64 = "c" * 64
    src = tmp_path / "bundles" / f"{hex64}.zip"
    src.write_bytes(b"payload")

    resp = await bucket_client.post(
        "/api/bucket/move",
        json={"sources": [f"{hex64}.zip"], "dest_prefix": "renamed.zip"},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["keys"] == ["renamed.zip"]
    assert not src.exists()
    assert (tmp_path / "bundles" / "renamed.zip").exists()
