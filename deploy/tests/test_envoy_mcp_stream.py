"""Envoy routes for MCP stream and catalog (ext_authz + pool_dfp)."""

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
    marker = "envoy.yaml: |"
    start = manifest.index(marker) + len(marker)
    rest = manifest[start:]
    end = rest.find("\n---")
    return rest[:end] if end != -1 else rest


def test_mcp_stream_uses_ext_authz_and_pool_dfp() -> None:
    cfg = _envoy_config(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    assert "/v1/mcp/stream" in cfg
    stream_block = cfg.split("/v1/mcp/stream")[1].split("- match:")[0]
    assert "cluster: pool_dfp" in stream_block
    assert 'substitution: "/mcp"' in stream_block
    assert "ext_authz_direct" not in stream_block
    assert "disabled: true" not in stream_block
    assert "x-mcp-principal" in cfg


def test_mcp_catalog_uses_ext_authz_and_pool_dfp() -> None:
    cfg = _envoy_config(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    assert "/catalog" in cfg
    assert "pool_dfp" in cfg.split("/catalog")[1][:400]
    assert 'substitution: "/catalog"' in cfg
    assert "x-mcp-server" in cfg
