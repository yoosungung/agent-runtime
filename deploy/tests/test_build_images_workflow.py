"""Smoke tests for GHA build-images workflow."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/build-images.yml"
AGENT_DOCKERFILE = REPO_ROOT / "runtimes/agent-base/Dockerfile"


def test_build_images_workflow_stages_path_graph_for_agent_base() -> None:
    text = WORKFLOW.read_text()
    assert "matrix.image == 'backend' || matrix.image == 'agent-base'" in text


def test_agent_base_dockerfile_copies_path_graph_pipeline() -> None:
    text = AGENT_DOCKERFILE.read_text()
    assert "COPY path-graph/pipeline /path-graph/pipeline" in text
