"""Envoy routes MCP stream through ext_authz + pool_dfp (/mcp rewrite)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _kustomize_build(path: Path) -> str:
    return subprocess.check_output(
        ["kubectl", "kustomize", str(path)],
        text=True,
    )


def _envoy_config(manifest: str) -> str:
    return manifest.split("name: envoy-config")[1].split("kind: Deployment")[0]


def test_mcp_stream_uses_ext_authz_and_pool_dfp() -> None:
    cfg = _envoy_config(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    stream_block = cfg.split('path: "/v1/mcp/stream"')[1].split("- match:")[0]
    assert "cluster: pool_dfp" in stream_block
    assert 'substitution: "/mcp"' in stream_block
    assert "ext_authz_direct" not in stream_block
    assert "disabled: true" not in stream_block
    assert "x-mcp-principal" in cfg
