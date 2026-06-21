"""Kustomize smoke tests for pool NetworkPolicy and runtime/role labels."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

POOL_DEPLOYMENTS = (
    "agent-pool-compiled-graph.yaml",
    "agent-pool-adk.yaml",
    "mcp-pool-fastmcp.yaml",
    "mcp-pool-mcp-sdk.yaml",
)


def _kustomize_build(path: Path) -> str:
    return subprocess.check_output(
        ["kubectl", "kustomize", str(path)],
        text=True,
    )


def test_static_pool_deployments_carry_runtime_role_pool() -> None:
    base = REPO_ROOT / "deploy/k8s/base"
    for name in POOL_DEPLOYMENTS:
        text = (base / name).read_text()
        assert 'runtime/role: pool' in text, f"missing runtime/role label in {name}"


def test_base_kustomize_includes_pool_network_policies() -> None:
    manifest = _kustomize_build(REPO_ROOT / "deploy/k8s/base")
    assert "name: pool-ingress" in manifest
    assert "name: pool-egress" in manifest
    assert "runtime/role: pool" in manifest
    assert "app: envoy" in manifest.split("name: pool-ingress")[1].split("---")[0]
    assert "app: deploy-api" in manifest.split("name: pool-egress")[1]
    assert "app: backend" in manifest.split("name: pool-egress")[1]
    assert "port: 443" in manifest.split("name: pool-egress")[1]
