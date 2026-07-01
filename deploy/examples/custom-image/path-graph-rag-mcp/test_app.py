"""Unit tests for path-graph-rag-mcp invoke handler."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_EXAMPLE_DIR = Path(__file__).resolve().parent
if str(_EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_DIR))

from app import app  # noqa: E402


def test_healthz() -> None:
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_invoke_search() -> None:
    client = TestClient(app)
    with patch("path_graph.rag.hybrid_search.hybrid_search") as mock_search:
        mock_search.return_value = [{"id": "c1", "text": "hit", "rrf_score": 0.5}]
        cfg_b64 = base64.b64encode(
            json.dumps({"path_graph_rag": {"default_top_k": 5}}).encode()
        ).decode()
        r = client.post(
            "/invoke",
            headers={"x-runtime-cfg": cfg_b64},
            json={
                "server": "path-graph-rag",
                "tool": "search",
                "arguments": {
                    "query": "hello",
                    "tenant": "dev",
                    "project_id": "p1",
                    "project_slug": "default",
                },
            },
        )
    assert r.status_code == 200
    assert r.json()["result"]["results"][0]["id"] == "c1"
    mock_search.assert_called_once()


def test_invoke_unknown_tool() -> None:
    client = TestClient(app)
    r = client.post(
        "/invoke",
        json={"server": "x", "tool": "embed", "arguments": {}},
    )
    assert r.status_code == 400
