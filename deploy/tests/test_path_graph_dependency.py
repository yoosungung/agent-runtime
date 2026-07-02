"""Contract tests for path-graph wheel dependency (no editable path staging)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PATH_GRAPH_VERSION = "0.1.1"
PATH_GRAPH_WHEEL_URL = (
    f"https://github.com/yoosungung/path-graph/releases/download/"
    f"v{PATH_GRAPH_VERSION}/path_graph-{PATH_GRAPH_VERSION}-py3-none-any.whl"
)


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def test_backend_uses_release_wheel_not_editable_path() -> None:
    text = _read("backend/pyproject.toml")
    assert 'path = "../../path-graph' not in text
    assert f"path-graph=={PATH_GRAPH_VERSION}" in text
    assert PATH_GRAPH_WHEEL_URL in text


def test_agent_base_has_no_path_graph_dependency() -> None:
    text = _read("runtimes/agent-base/pyproject.toml")
    assert "path-graph" not in text


def test_root_pyproject_has_no_path_graph_editable() -> None:
    text = _read("pyproject.toml")
    assert "path-graph" not in text or "editable" not in text


def test_uv_lock_backend_wheel_not_editable() -> None:
    text = _read("uv.lock")
    assert "editable = \"../path-graph/pipeline\"" not in text
    assert PATH_GRAPH_WHEEL_URL in text
