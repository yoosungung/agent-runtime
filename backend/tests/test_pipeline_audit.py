from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.pipeline_audit.actions import build_audit_details, resolve_audit_action
from backend.pipeline_audit.register import install_pipeline_console_audit
from runtime_common.db.models import AuditLogRow, Base
from runtime_common.schemas import Principal

TEST_DSN = "sqlite+aiosqlite:///:memory:"
_CSRF = "test-csrf-token-value"
_ADMIN_PRINCIPAL = Principal(
    sub="admin",
    user_id=1,
    tenant="dev",
    access=[],
    grace_applied=False,
    role="admin",
    must_change_password=False,
)


def test_resolve_audit_action_maps_project_create():
    assert resolve_audit_action({"POST"}, "/projects") == "pipeline.project.create"


def test_resolve_audit_action_skips_dry_run_test():
    assert resolve_audit_action({"POST"}, "/sources/{source_id}/test") is None


def test_resolve_audit_action_skips_get():
    assert resolve_audit_action({"GET"}, "/projects") is None


def test_build_audit_details_includes_domain_and_tenant():
    details = build_audit_details(
        "pipeline.project.create",
        kwargs={},
        result=SimpleNamespace(id="proj-1", slug="demo", name="Demo"),
        principal=_ADMIN_PRINCIPAL,
    )
    assert details["domain"] == "pipeline"
    assert details["tenant"] == "dev"
    assert details["project_id"] == "proj-1"
    assert details["slug"] == "demo"


def test_build_audit_details_redacts_credential_secrets():
    body = SimpleNamespace(secrets={"refresh_token": "secret-value"})
    details = build_audit_details(
        "pipeline.credential.secrets_put",
        kwargs={"credential_id": "cred-1", "body": body},
        result=None,
        principal=_ADMIN_PRINCIPAL,
    )
    assert details["credential_id"] == "cred-1"
    assert details["secret_keys"] == ["refresh_token"]
    assert "secrets" not in details


@pytest_asyncio.fixture
async def pipeline_audit_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from path_graph.contracts.project import ProjectProfile
    from path_graph.contracts.source import SourceDriver, SourceProfile

    import backend.deps as _deps_mod
    from backend.bundle_storage import LocalBundleStorage
    from backend.object_store_browser import LocalObjectStoreBrowser
    from backend.routers import pipeline as pipeline_router_module
    from backend.routers import pipeline_credentials as pipeline_credentials_router_module
    from backend.settings import Settings
    from runtime_common.auth import AuthClient

    app = FastAPI()
    storage_dir = tmp_path / "bundles"
    storage_dir.mkdir()

    settings = Settings(
        POSTGRES_DSN=TEST_DSN,
        AUTH_URL="http://auth-mock",
        INITIAL_ADMIN_PASSWORD="",
        INITIAL_ADMIN_PASSWORD_FILE="",
        BUNDLE_STORAGE_DIR=str(storage_dir),
        SESSION_COOKIE_SECURE=False,
        ALLOW_HARD_DELETE=False,
        BACKEND_SERVE_SPA=False,
        PIPELINE_CONSOLE_ENABLED=True,
        PATH_GRAPH_DSN="postgresql://localhost/test",
        PIPELINE_CREDENTIAL_LOCAL_DIR=str(tmp_path / "pipeline-creds"),
    )
    app.dependency_overrides[_deps_mod.get_settings] = lambda: settings
    monkeypatch.setattr(_deps_mod, "validate_csrf", lambda header, cookie: True)

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.settings = settings

    bundle_storage = LocalBundleStorage(str(storage_dir))
    await bundle_storage.ensure_ready()
    app.state.bundle_storage = bundle_storage
    app.state.object_store_browser = LocalObjectStoreBrowser(str(storage_dir))
    app.state.vfs_agent_store = None
    app.state.vfs_pool = None

    mock_auth = AsyncMock(spec=AuthClient)
    mock_auth.verify = AsyncMock(return_value=_ADMIN_PRINCIPAL)
    app.state.auth_client = mock_auth

    from backend.pool_status import PoolRegistryMonitor

    app.state.pool_monitor = PoolRegistryMonitor("")

    project = ProjectProfile(tenant="dev", id="550e8400-e29b-41d4-a716-446655440000", slug="default", name="Default")
    source = SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id=project.id,
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "docs"},
    )

    mock_store = MagicMock()
    mock_store.list_sources.return_value = [source]
    mock_store.get_source.return_value = source
    mock_store.create_source.return_value = source
    mock_store.list_pipeline_runs.return_value = []
    mock_store.list_documents_summary.return_value = []

    mock_project_store = MagicMock()
    mock_project_store.list_projects.return_value = [project]
    mock_project_store.get_project.return_value = project
    mock_project_store.create_project.return_value = project

    install_pipeline_console_audit(
        app,
        pipeline_router_module.router,
        pipeline_credentials_router_module.router,
    )
    app.include_router(pipeline_router_module.router)
    app.include_router(pipeline_credentials_router_module.router)

    with patch("backend.routers.pipeline.SourceStore", return_value=mock_store):
        with patch("backend.routers.pipeline.ProjectStore", return_value=mock_project_store):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"access_token": "valid-token", "csrf_token": _CSRF},
            ) as client:
                yield client, session_factory

    app.dependency_overrides.pop(_deps_mod.get_settings, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_project_writes_pipeline_audit_log(pipeline_audit_client):
    client, session_factory = pipeline_audit_client
    resp = await client.post(
        "/api/pipeline/projects",
        json={"name": "New Project", "slug": "new-project"},
        headers={"X-CSRF-Token": _CSRF},
    )
    assert resp.status_code == 201

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(AuditLogRow).where(AuditLogRow.action == "pipeline.project.create")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].actor == "admin"
    assert rows[0].details["domain"] == "pipeline"
    assert rows[0].details["project_id"] == "550e8400-e29b-41d4-a716-446655440000"
