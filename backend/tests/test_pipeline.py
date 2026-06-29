from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
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
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
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
        project_id="550e8400-e29b-41d4-a716-446655440000",
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정"},
    )


def _project_obj():
    from path_graph.contracts.project import ProjectProfile

    return ProjectProfile(
        tenant="dev",
        id="550e8400-e29b-41d4-a716-446655440000",
        slug="default",
        name="Default",
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

    mock_project_store = MagicMock()
    mock_project_store.list_projects.return_value = [_project_obj()]
    mock_project_store.get_project.return_value = _project_obj()
    mock_project_store.create_project.return_value = _project_obj()

    with patch("backend.routers.pipeline.SourceStore", return_value=mock_store):
        with patch("backend.routers.pipeline.ProjectStore", return_value=mock_project_store):
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
                yield ac, mock_store, mock_project_store

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_sources(pipeline_client):
    client, _mock_store, _mock_project_store = pipeline_client
    resp = await client.get("/api/pipeline/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["items"][0]["name"] == "kms"
    assert data["items"][0]["project_id"] == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_list_projects(pipeline_client):
    client, _mock_store, mock_project_store = pipeline_client
    resp = await client.get("/api/pipeline/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["slug"] == "default"
    mock_project_store.list_projects.assert_called_once_with("dev")


@pytest.mark.asyncio
async def test_create_project(pipeline_client, monkeypatch):
    from unittest.mock import AsyncMock

    client, _mock_store, mock_project_store = pipeline_client
    sync_mock = AsyncMock()
    monkeypatch.setattr("backend.routers.pipeline._sync_project_reconcile_cron", sync_mock)

    resp = await client.post(
        "/api/pipeline/projects",
        headers=_csrf_headers(),
        json={"name": "Product Docs", "slug": "product-docs"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "default"
    mock_project_store.create_project.assert_called_once()
    sync_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_project_invalid_slug_returns_422(pipeline_client):
    client, _mock_store, mock_project_store = pipeline_client
    mock_project_store.create_project.side_effect = ValueError("invalid project slug")
    resp = await client.post(
        "/api/pipeline/projects",
        headers=_csrf_headers(),
        json={"name": "Docs", "slug": "###"},
    )
    assert resp.status_code == 422
    assert "invalid project slug" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_source(pipeline_client):
    client, mock_store, _mock_project_store = pipeline_client
    resp = await client.post(
        "/api/pipeline/sources",
        headers=_csrf_headers(),
        json={
            "project_id": "550e8400-e29b-41d4-a716-446655440000",
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
    client, _, _ = pipeline_client
    resp = await client.get("/api/pipeline/sources")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_test_source(pipeline_client, monkeypatch):
    client, _mock_store, _mock_project_store = pipeline_client
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
    client, mock_store, _mock_project_store = pipeline_client
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
async def test_run_rejects_when_workflow_running(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    from path_graph.contracts.source import SourceDriver, SourceProfile

    mock_store.get_source.return_value = SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id="550e8400-e29b-41d4-a716-446655440000",
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정"},
        enabled=True,
        last_batch_id="batch-prev",
        last_run_status="submitted",
    )
    mock_store.get_pipeline_run_by_batch.return_value = {
        "id": "run-1",
        "workflow_name": "collect-kms-xyz",
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
        "/api/pipeline/sources/11111111-1111-4111-8111-111111111111/run",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 409
    assert "이미 수행 중" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_source_workflow_status_active(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
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

    resp = await client.get(
        "/api/pipeline/sources/22222222-2222-4222-8222-222222222222/workflow-status",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert data["workflow_name"] == "ingest-manual-docs-xyz"
    assert data["phase"] == "Running"
    assert data["batch_id"] == "batch-prev"


@pytest.mark.asyncio
async def test_source_workflow_status_idle(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    mock_store.get_source.return_value = _manual_profile(last_batch_id=None, last_run_status=None)

    resp = await client.get(
        "/api/pipeline/sources/22222222-2222-4222-8222-222222222222/workflow-status",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False


@pytest.mark.asyncio
async def test_source_workflow_status_argo_unavailable(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    mock_store.get_source.return_value = _manual_profile()
    mock_store.get_pipeline_run_by_batch.return_value = {
        "id": "run-1",
        "workflow_name": "ingest-manual-docs-xyz",
        "argo_uid": "uid-1",
        "batch_id": "batch-prev",
        "status": "submitted",
    }

    async def _argo_down(**_kwargs):
        raise HTTPException(status_code=503, detail="Argo Workflows unavailable")

    monkeypatch.setattr(
        "backend.pipeline_helpers.get_workflow_phase",
        _argo_down,
    )

    resp = await client.get(
        "/api/pipeline/sources/22222222-2222-4222-8222-222222222222/workflow-status",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["argo_available"] is False
    assert data["active"] is True
    assert data["workflow_name"] == "ingest-manual-docs-xyz"


@pytest.mark.asyncio
async def test_source_not_found(pipeline_client):
    client, mock_store, _mock_project_store = pipeline_client
    mock_store.get_source.return_value = None
    resp = await client.get("/api/pipeline/sources/00000000-0000-4000-8000-000000000001")
    assert resp.status_code == 404


def test_source_driver_includes_manual():
    from path_graph.contracts.source import SourceDriver

    assert SourceDriver.MANUAL.value == "manual"


@pytest.mark.asyncio
async def test_create_manual_source(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    from path_graph.contracts.source import SourceDriver, SourceProfile

    manual = SourceProfile(
        tenant="dev",
        id="22222222-2222-4222-8222-222222222222",
        project_id="550e8400-e29b-41d4-a716-446655440000",
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
            "project_id": "550e8400-e29b-41d4-a716-446655440000",
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
        "project_id": "550e8400-e29b-41d4-a716-446655440000",
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
    client, mock_store, _mock_project_store = pipeline_client
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
async def test_create_source_requires_project(pipeline_client):
    client, _mock_store, _mock_project_store = pipeline_client
    resp = await client.post(
        "/api/pipeline/sources",
        headers=_csrf_headers(),
        json={
            "name": "kms",
            "driver": "sharepoint",
            "source_id": "sharepoint:kms",
            "config": {},
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_unknown_project(pipeline_client):
    client, _mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = None
    resp = await client.post(
        "/api/pipeline/sources",
        headers=_csrf_headers(),
        json={
            "project_id": "00000000-0000-4000-8000-000000000001",
            "name": "kms",
            "driver": "sharepoint",
            "source_id": "sharepoint:kms",
            "config": {},
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ingest_allows_when_workflow_finished(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
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


@pytest.mark.asyncio
async def test_get_project(pipeline_client):
    client, _mock_store, mock_project_store = pipeline_client
    resp = await client.get(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000",
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "default"
    mock_project_store.get_project.assert_called_with(
        "dev", "550e8400-e29b-41d4-a716-446655440000"
    )


@pytest.mark.asyncio
async def test_list_sources_filtered_by_project(pipeline_client):
    client, mock_store, _mock_project_store = pipeline_client
    resp = await client.get(
        "/api/pipeline/sources",
        params={"project_id": "550e8400-e29b-41d4-a716-446655440000"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


@pytest.mark.asyncio
async def test_list_project_documents(pipeline_client, monkeypatch):
    client, _mock_store, mock_project_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.list_documents_for_project",
        lambda tenant, project_id, **kwargs: [
            {
                "document_id": "doc-1",
                "source_id": "manual:docs",
                "project_id": project_id,
                "content_hash": "sha256:abc",
                "ingest_state": "pending",
                "s3_raw_uri": "s3://b/raw/dev/p/manual/docs/sha256:abc/file.pdf",
                "filename": "file.pdf",
            }
        ],
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.count_documents_for_project",
        lambda tenant, project_id, **kwargs: 1,
    )
    resp = await client.get(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/documents",
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "file.pdf"


@pytest.mark.asyncio
async def test_submit_project_purge_success(pipeline_client, monkeypatch):
    from unittest.mock import AsyncMock

    client, mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = _project_obj()

    monkeypatch.setattr(
        "backend.routers.pipeline.assert_project_lifecycle_idle",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.mark_project_lifecycle_started",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.submit_purge_project",
        AsyncMock(
            return_value={"workflow_name": "purge-default-abc", "argo_uid": "uid-purge"}
        ),
    )

    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/purge",
        headers=_csrf_headers(),
        json={"reason": "test"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow_name"] == "purge-default-abc"
    assert data["run_kind"] == "purge"
    mock_store.insert_pipeline_run.assert_called_once()
    assert mock_store.insert_pipeline_run.call_args.kwargs.get("run_kind") == "purge"


@pytest.mark.asyncio
async def test_submit_project_delete_success(pipeline_client, monkeypatch):
    from unittest.mock import AsyncMock

    client, mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = _project_obj()

    monkeypatch.setattr(
        "backend.routers.pipeline.assert_project_lifecycle_idle",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.mark_project_lifecycle_started",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.submit_delete_project",
        AsyncMock(
            return_value={"workflow_name": "delete-default-abc", "argo_uid": "uid-del"}
        ),
    )

    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/delete",
        headers=_csrf_headers(),
        json={"reason": "test"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow_name"] == "delete-default-abc"
    assert data["run_kind"] == "delete"
    mock_store.insert_pipeline_run.assert_called_once()
    assert mock_store.insert_pipeline_run.call_args.kwargs.get("run_kind") == "delete"


@pytest.mark.asyncio
async def test_purge_document(pipeline_client, monkeypatch):
    client, _mock_store, _mock_project_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.api_purge_document",
        lambda tenant, doc_id, **kwargs: {"status": "purged", "document_id": doc_id},
    )
    resp = await client.post(
        "/api/pipeline/documents/doc-1/purge",
        headers=_csrf_headers(),
        json={"reason": "test", "hard_raw": False},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "purged"


@pytest.mark.asyncio
async def test_list_tombstones(pipeline_client, monkeypatch):
    client, _mock_store, _mock_project_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.api_list_tombstones",
        lambda tenant, project_id=None: [{"content_hash": "sha256:abc"}],
    )
    resp = await client.get(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/tombstones",
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


@pytest.mark.asyncio
async def test_reconcile_project(pipeline_client, monkeypatch):
    client, _mock_store, _mock_project_store = pipeline_client
    monkeypatch.setattr(
        "backend.routers.pipeline.api_reconcile_project",
        lambda tenant, project_id: {"orphans_removed": 2},
    )
    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/reconcile",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["orphans_removed"] == 2


@pytest.mark.asyncio
async def test_list_runs_enriched_from_argo(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    mock_store.list_pipeline_runs.return_value = [
        {
            "id": "run-1",
            "workflow_name": "ingest-manual-docs-xyz",
            "argo_uid": "uid-1",
            "batch_id": "20260626-120000",
            "status": "submitted",
            "started_at": None,
            "ended_at": None,
        }
    ]

    async def _status(**_kwargs):
        return {
            "phase": "Succeeded",
            "started_at": "2026-06-26T12:00:01Z",
            "ended_at": "2026-06-26T12:05:00Z",
        }

    monkeypatch.setattr(
        "backend.pipeline_helpers.get_workflow_status",
        _status,
    )

    resp = await client.get("/api/pipeline/runs", headers=_csrf_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["argo_available"] is True
    assert data["items"][0]["status"] == "Succeeded"
    assert data["items"][0]["started_at"] == "2026-06-26T12:00:01Z"
    assert data["items"][0]["ended_at"] == "2026-06-26T12:05:00Z"


@pytest.mark.asyncio
async def test_list_sources_pagination(pipeline_client):
    client, mock_store, _mock_project_store = pipeline_client
    other = _profile_obj()
    other.name = "other"
    mock_store.list_sources.return_value = [_profile_obj(), other]

    resp = await client.get(
        "/api/pipeline/sources",
        params={"limit": 1, "offset": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "other"


@pytest.mark.asyncio
async def test_list_project_documents_pagination(pipeline_client, monkeypatch):
    client, _mock_store, _mock_project_store = pipeline_client
    project_id = "550e8400-e29b-41d4-a716-446655440000"

    def _list_docs(tenant, pid, **kwargs):
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20
        assert kwargs["filename_contains"] == "report"
        return [
            {
                "document_id": "doc-1",
                "source_id": "manual:docs",
                "project_id": pid,
                "content_hash": "sha256:abc",
                "ingest_state": "pending",
                "s3_raw_uri": "s3://b/raw/dev/p/manual/docs/sha256:abc/report.pdf",
                "filename": "report.pdf",
            }
        ]

    def _count_docs(tenant, pid, **kwargs):
        assert kwargs["filename_contains"] == "report"
        return 31

    monkeypatch.setattr("backend.routers.pipeline.list_documents_for_project", _list_docs)
    monkeypatch.setattr("backend.routers.pipeline.count_documents_for_project", _count_docs)

    resp = await client.get(
        f"/api/pipeline/projects/{project_id}/documents",
        params={"limit": 10, "offset": 20, "filename": "report"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 31
    assert data["limit"] == 10
    assert data["offset"] == 20
    assert len(data["items"]) == 1
    assert data["items"][0]["filename"] == "report.pdf"


@pytest.mark.asyncio
async def test_list_runs_pagination(pipeline_client, monkeypatch):
    client, mock_store, _mock_project_store = pipeline_client
    mock_store.list_pipeline_runs.return_value = [
        {
            "id": "run-2",
            "workflow_name": "ingest-b",
            "argo_uid": None,
            "batch_id": "batch-2",
            "status": "Succeeded",
            "started_at": "2026-06-26T13:00:00Z",
            "ended_at": "2026-06-26T13:05:00Z",
        }
    ]
    mock_store.count_pipeline_runs.return_value = 75

    async def _enrich(**kwargs):
        return kwargs["runs"], True

    monkeypatch.setattr(
        "backend.routers.pipeline.enrich_pipeline_runs_with_argo",
        _enrich,
    )

    resp = await client.get(
        "/api/pipeline/runs",
        params={"limit": 25, "offset": 50},
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 75
    assert data["limit"] == 25
    assert data["offset"] == 50
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "run-2"
    mock_store.list_pipeline_runs.assert_called_once_with("dev", 25, 50)


@pytest.mark.asyncio
async def test_submit_project_graphrag_success(pipeline_client, monkeypatch):
    from path_graph.admin.downstream import DownstreamBusyError, DownstreamValidationError
    from unittest.mock import AsyncMock, MagicMock

    client, mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = _project_obj()

    plan = MagicMock(
        project_id="550e8400-e29b-41d4-a716-446655440000",
        project_slug="default",
        batch_id="20260101-120000",
        chunks_key="chunks/dev/550e8400-e29b-41d4-a716-446655440000/20260101-120000/chunks.jsonl",
        document_count=2,
    )

    monkeypatch.setattr(
        "backend.routers.pipeline.prepare_graphrag_submission",
        lambda *args, **kwargs: plan,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.assert_project_graphrag_idle",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.submit_graphrag",
        AsyncMock(
            return_value={"workflow_name": "graphrag-default-abc", "argo_uid": "uid-1"}
        ),
    )

    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/graphrag",
        headers=_csrf_headers(),
        json={"batch_id": "20260101-120000"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["batch_id"] == "20260101-120000"
    assert data["document_count"] == 2
    assert data["workflow_name"] == "graphrag-default-abc"
    assert data["workflow_template"] == "pipeline-graphrag"
    mock_store.insert_pipeline_run.assert_called()
    assert mock_store.insert_pipeline_run.call_args.kwargs.get("run_kind") == "graphrag"


@pytest.mark.asyncio
async def test_submit_project_graphrag_validation_error(pipeline_client, monkeypatch):
    from path_graph.admin.downstream import DownstreamValidationError

    client, _mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = _project_obj()

    def _raise(*args, **kwargs):
        raise DownstreamValidationError("no indexed_rag documents")

    monkeypatch.setattr("backend.routers.pipeline.prepare_graphrag_submission", _raise)

    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/graphrag",
        headers=_csrf_headers(),
        json={"batch_id": "bad-batch"},
    )
    assert resp.status_code == 400
    assert "indexed_rag" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_submit_project_graphrag_busy(pipeline_client, monkeypatch):
    from path_graph.admin.downstream import DownstreamBusyError
    from unittest.mock import MagicMock

    client, _mock_store, mock_project_store = pipeline_client
    mock_project_store.get_project.return_value = _project_obj()

    plan = MagicMock(
        project_id="550e8400-e29b-41d4-a716-446655440000",
        project_slug="default",
        batch_id="20260101-120000",
        chunks_key="chunks/x",
        document_count=1,
    )
    monkeypatch.setattr(
        "backend.routers.pipeline.prepare_graphrag_submission",
        lambda *args, **kwargs: plan,
    )

    def _busy(*args, **kwargs):
        raise DownstreamBusyError("active workflow")

    monkeypatch.setattr("backend.routers.pipeline.assert_project_graphrag_idle", _busy)

    resp = await client.post(
        "/api/pipeline/projects/550e8400-e29b-41d4-a716-446655440000/graphrag",
        headers=_csrf_headers(),
        json={"batch_id": "20260101-120000"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_runs_filters_by_project_id(pipeline_client, monkeypatch):
    from unittest.mock import AsyncMock

    client, mock_store, _mock_project_store = pipeline_client
    mock_store.count_pipeline_runs.return_value = 1
    mock_store.list_pipeline_runs.return_value = [
        {
            "id": "run-1",
            "workflow_name": "graphrag-default-x",
            "argo_uid": None,
            "batch_id": "b1",
            "status": "Succeeded",
            "started_at": None,
            "ended_at": None,
            "project_id": "550e8400-e29b-41d4-a716-446655440000",
            "run_kind": "graphrag",
        }
    ]
    monkeypatch.setattr(
        "backend.routers.pipeline.enrich_pipeline_runs_with_argo",
        AsyncMock(return_value=(mock_store.list_pipeline_runs.return_value, True)),
    )

    resp = await client.get(
        "/api/pipeline/runs?project_id=550e8400-e29b-41d4-a716-446655440000",
        headers=_csrf_headers(),
    )
    assert resp.status_code == 200
    mock_store.list_pipeline_runs.assert_called_once()
    assert mock_store.list_pipeline_runs.call_args.kwargs["project_id"] == (
        "550e8400-e29b-41d4-a716-446655440000"
    )
