"""Smoke tests for GHA build-images workflow."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/build-images.yml"
AGENT_DOCKERFILE = REPO_ROOT / "runtimes/agent-base/Dockerfile"
RAG_MCP_DOCKERFILE = (
    REPO_ROOT / "deploy/examples/custom-image/path-graph-rag-mcp/Dockerfile"
)

_PATH_GRAPH_IMAGES = frozenset({"backend", "agent-base", "path-graph-rag-mcp"})


def test_build_images_workflow_stages_path_graph_for_embedded_images() -> None:
    text = WORKFLOW.read_text()
    for image in _PATH_GRAPH_IMAGES:
        assert image in text
    assert re.search(
        r'contains\(fromJSON\(\'\["backend", "agent-base", "path-graph-rag-mcp"\]\'\), matrix\.image\)',
        text,
    )


def test_build_images_workflow_stages_path_graph_for_uv_sibling() -> None:
    text = WORKFLOW.read_text()
    assert "mkdir -p ../path-graph" in text
    assert "_path_graph_repo" in text


def test_build_images_workflow_includes_path_graph_rag_mcp_matrix() -> None:
    text = WORKFLOW.read_text()
    assert "image: path-graph-rag-mcp" in text
    assert "deploy/examples/custom-image/path-graph-rag-mcp/Dockerfile" in text


def test_agent_base_dockerfile_copies_path_graph_pipeline() -> None:
    text = AGENT_DOCKERFILE.read_text()
    assert "COPY path-graph/pipeline /path-graph/pipeline" in text


def test_path_graph_rag_mcp_dockerfile_copies_path_graph_pipeline() -> None:
    text = RAG_MCP_DOCKERFILE.read_text()
    assert "COPY path-graph/pipeline /path-graph/pipeline" in text


def test_path_graph_rag_mcp_workflow_exists() -> None:
    workflow = REPO_ROOT / ".github/workflows/path-graph-rag-mcp.yml"
    text = workflow.read_text()
    assert "deploy/examples/custom-image/path-graph-rag-mcp/Dockerfile" in text
    assert "path-graph-rag-mcp/test_app.py" in text
    assert "github.event_name != 'pull_request'" in text
