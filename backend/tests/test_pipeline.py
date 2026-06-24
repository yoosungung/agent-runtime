from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
_USER_PRINCIPAL = {**_ADMIN_PRINCIPAL, "role": "user"}
_NO_TENANT_PRINCIPAL = {**_ADMIN_PRINCIPAL, "tenant": None}

_SAMPLE_PROFILE = {
    "tenant": "dev",
    "id": "11111111-1111-4111-8111-111111111111",
    "name": "kms",
    "driver": "sharepoint",
    "source_id": "sharepoint:kms",
    "config": {"folder": "회사규정"},
    "enabled": True,
    "schedule_cron": None,
    "last_batch_id": None,
    "last_run_at": None,
    "last_run_status": None,
    "created_at": None,
    "updated_at": None,
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
        BUNDLE_STORAGE_DIR="/tmp/pipeline-test",
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
        PIPELINE_CONSOLE_ENABLED=True,
        PATH_GRAPH_DSN="postgresql://localhost/test",
    )
    return _settings_mod.Settings(**{**defaults, **overrides})


def _profile_obj():
    from path_graph.contracts.source import SourceDriver, SourceProfile

    return SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정"},
    )


@pytest_asyncio.fixture
async def pipeline_client(tmp_path, monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from backend.bundle_storage import LocalBundleStorage
    from backend.object_store_browser import LocalObjectStoreBrowser
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    storage_dir = tmp_path / "bundles"
    storage_dir.mkdir()

    _settings = _make_test_settings(
        BUNDLE_STORAGE_DIR=str(storage_dir),
        PIPELINE_CREDENTIAL_LOCAL_DIR=str(tmp_path / "pipeline-creds"),
    )
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
    app.state.vfs_agent_store = None
    app.state.vfs_pool = None

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_ADMIN_PRINCIPAL))
    app.state.auth_client = mock_auth

    from backend.pool_status import PoolRegistryMonitor

    app.state.pool_monitor = PoolRegistryMonitor("")

    mock_store = MagicMock()
    mock_store.list_sources.return_value = [_profile_obj()]
    mock_store.get_source.return_value = _profile_obj()
    mock_store.create_source.return_value = _profile_obj()
    mock_store.update_source.return_value = _profile_obj()
    mock_store.delete_source.return_value = True
    mock_store.list_pipeline_runs.return_value = []
    mock_store.list_documents_summary.return_value = []

    with patch("backend.routers.pipeline.SourceStore", return_value=mock_store):
        with patch(
            "backend.routers.pipeline.pg_settings_for_source",
            new_callable=AsyncMock,
        ) as mock_pg:
            from path_graph.config import Settings as PgSettings

            mock_pg.return_value = PgSettings()
            transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"access_token": "valid-token", "csrf_token": _CSRF},
        ) as ac:
            yield ac, mock_store

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_sources(pipeline_client):
    client, _mock_store = pipeline_client
    resp = await client.get("/api/pipeline/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "kms"


@pytest.mark.asyncio
async def test_create_source(pipeline_client):
    client, mock_store = pipeline_client
    resp = await client.post(
        "/api/pipeline/sources",
        headers=_csrf_headers(),
        json={
            "name": "kms",
            "driver": "sharepoint",
            "source_id": "sharepoint:kms",
            "config": {"folder": "회사규정"},
        },
    )
    assert resp.status_code == 201
    assert resp.json()["driver"] == "sharepoint"
    mock_store.create_source.assert_called_once()


@pytest.mark.asyncio
async def test_non_admin_forbidden(tmp_path, monkeypatch):
    import backend.deps as _deps_mod
    from backend.app import app
    from runtime_common.auth import AuthClient
    from runtime_common.schemas import Principal

    _settings = _make_test_settings(
        BUNDLE_STORAGE_DIR=str(tmp_path / "b"),
        PIPELINE_CREDENTIAL_LOCAL_DIR=str(tmp_path / "pipeline-creds"),
    )
    app.dependency_overrides[_deps_mod.get_settings] = lambda: _settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=Principal.model_validate(_USER_PRINCIPAL))
    app.state.auth_client = mock_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"access_token": "valid-token", "csrf_token": _CSRF},
    ) as ac:
        resp = await ac.get("/api/pipeline/sources")
    assert resp.status_code == 403
    app.dependency_overrides.pop(_deps_mod.get_settings, None)


@pytest.mark.asyncio
async def test_missing_tenant_forbidden(pipeline_client):
    import backend.deps as _deps_mod
    from backend.app import app
    from runtime_common.schemas import Principal

    app.state.auth_client.verify = AsyncMock(
        return_value=Principal.model_validate(_NO_TENANT_PRINCIPAL)
    )
    client, _ = pipeline_client
    resp = await client.get("/api/pipeline/sources")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_test_source(pipeline_client, monkeypatch):
    client, _mock_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.probe_source",
        lambda profile, settings=None: {"file_count": 3, "sample_names": ["a.pdf"]},
    )
    resp = await client.post(
        "/api/pipeline/sources/11111111-1111-4111-8111-111111111111/test",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["file_count"] == 3


@pytest.mark.asyncio
async def test_run_source(pipeline_client, monkeypatch):
    client, mock_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.submit_collect_ingest_rag",
        AsyncMock(return_value={"workflow_name": "collect-kms-abc", "argo_uid": "uid-1"}),
    )
    resp = await client.post(
        "/api/pipeline/sources/11111111-1111-4111-8111-111111111111/run",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow_name"] == "collect-kms-abc"
    assert data["batch_id"]
    assert data["file_count"] is None
    mock_store.record_run.assert_called_once()
    mock_store.insert_pipeline_run.assert_called_once()


@pytest.mark.asyncio
async def test_source_not_found(pipeline_client):
    client, mock_store = pipeline_client
    mock_store.get_source.return_value = None
    resp = await client.get("/api/pipeline/sources/00000000-0000-4000-8000-000000000001")
    assert resp.status_code == 404


def test_source_driver_includes_manual():
    from path_graph.contracts.source import SourceDriver

    assert SourceDriver.MANUAL.value == "manual"


@pytest.mark.asyncio
async def test_create_manual_source(pipeline_client, monkeypatch):
    client, mock_store = pipeline_client
    from path_graph.contracts.source import SourceDriver, SourceProfile

    manual = SourceProfile(
        tenant="dev",
        id="22222222-2222-4222-8222-222222222222",
        name="manual-docs",
        driver=SourceDriver.MANUAL,
        source_id="manual:docs",
        config={"allowed_extensions": ".pdf"},
    )
    mock_store.create_source.return_value = manual
    resp = await client.post(
        "/api/pipeline/sources",
        headers=_csrf_headers(),
        json={
            "name": "manual-docs",
            "driver": "manual",
            "source_id": "manual:docs",
            "config": {"allowed_extensions": ".pdf", "max_file_mb": 100},
        },
    )
    assert resp.status_code == 201
    assert resp.json()["driver"] == "manual"


def _manual_profile(**overrides):
    from path_graph.contracts.source import SourceDriver, SourceProfile

    defaults = {
        "tenant": "dev",
        "id": "22222222-2222-4222-8222-222222222222",
        "name": "manual-docs",
        "driver": SourceDriver.MANUAL,
        "source_id": "manual:docs",
        "config": {},
        "enabled": True,
        "last_batch_id": "batch-prev",
        "last_run_status": "submitted",
    }
    defaults.update(overrides)
    return SourceProfile(**defaults)


@pytest.mark.asyncio
async def test_ingest_rejects_when_workflow_running(pipeline_client, monkeypatch):
    client, mock_store = pipeline_client
    mock_store.get_source.return_value = _manual_profile()
    mock_store.get_pipeline_run_by_batch.return_value = {
        "id": "run-1",
        "workflow_name": "ingest-manual-docs-xyz",
        "argo_uid": "uid-1",
        "batch_id": "batch-prev",
        "status": "submitted",
    }

    async def _running_phase(**_kwargs):
        return "Running"

    monkeypatch.setattr(
        "backend.pipeline_helpers.get_workflow_phase",
        _running_phase,
    )

    resp = await client.post(
        "/api/pipeline/sources/22222222-2222-4222-8222-222222222222/ingest",
        headers=_csrf_headers(),
        json={"document_ids": []},
    )
    assert resp.status_code == 409
    assert "이미 수행 중" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_allows_when_workflow_finished(pipeline_client, monkeypatch):
    client, mock_store = pipeline_client
    mock_store.get_source.return_value = _manual_profile()
    mock_store.get_pipeline_run_by_batch.return_value = {
        "id": "run-1",
        "workflow_name": "ingest-manual-docs-xyz",
        "argo_uid": "uid-1",
        "batch_id": "batch-prev",
        "status": "submitted",
    }

    async def _succeeded_phase(**_kwargs):
        return "Succeeded"

    monkeypatch.setattr(
        "backend.pipeline_helpers.get_workflow_phase",
        _succeeded_phase,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.build_ingest_manifest",
        lambda *args, **kwargs: {
            "batch_id": "batch-new",
            "manifest_key": "manifest/key",
            "file_count": 0,
        },
    )

    resp = await client.post(
        "/api/pipeline/sources/22222222-2222-4222-8222-222222222222/ingest",
        headers=_csrf_headers(),
        json={"document_ids": []},
    )
    assert resp.status_code == 202
    assert resp.json()["batch_id"] == "batch-new"
