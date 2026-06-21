"""GET /catalog returns tools, resources, and prompts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mcp_base.app import app


@pytest.fixture
def catalog_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BUNDLE_CACHE_DIR", str(tmp_path / "bundles"))
    mock_deploy = AsyncMock()
    mock_deploy.resolve.return_value = MagicMock(
        source=MagicMock(runtime_pool="mcp:fastmcp", name="rag")
    )
    with TestClient(app) as client:
        app.state.deploy = mock_deploy
        app.state.loader = MagicMock()
        app.state.instance_cache = MagicMock()
        app.state.settings = MagicMock(runtime_kind="fastmcp")
        yield client


def test_catalog_returns_tools_resources_prompts(catalog_client: TestClient) -> None:
    with (
        patch("mcp_base.app.get_or_build_cached_instance", new_callable=AsyncMock) as mock_build,
        patch("mcp_base.app.runner_list_tools", new_callable=AsyncMock) as mock_tools,
        patch("mcp_base.app.runner_list_resources", new_callable=AsyncMock) as mock_resources,
        patch("mcp_base.app.runner_list_prompts", new_callable=AsyncMock) as mock_prompts,
    ):
        mock_build.return_value = MagicMock()
        mock_tools.return_value = [{"name": "search", "description": "Search"}]
        mock_resources.return_value = [{"name": "doc://readme", "description": "Readme"}]
        mock_prompts.return_value = [{"name": "summarize", "description": "Summarize"}]

        resp = catalog_client.get("/catalog", params={"server": "rag", "version": "v1"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["tools"] == [{"name": "search", "description": "Search"}]
        assert data["resources"] == [{"name": "doc://readme", "description": "Readme"}]
        assert data["prompts"] == [{"name": "summarize", "description": "Summarize"}]
