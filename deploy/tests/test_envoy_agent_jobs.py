"""Envoy routes for async agent jobs (POST/GET /v1/agents/jobs*)."""

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


def test_agent_jobs_route_rewrites_to_pool_jobs_path() -> None:
    cfg = _envoy_config(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    assert 'path_separated_prefix: "/v1/agents/jobs"' in cfg
    jobs_block = cfg.split('path_separated_prefix: "/v1/agents/jobs"')[1].split("- match:")[0]
    assert 'prefix_rewrite: "/jobs"' in jobs_block
    assert "pool_dfp" in jobs_block


def test_agent_invoke_route_lists_after_jobs_and_rewrites_to_invoke() -> None:
    cfg = _envoy_config(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    jobs_idx = cfg.index('path_separated_prefix: "/v1/agents/jobs"')
    invoke_idx = cfg.index('prefix: "/v1/agents/"', jobs_idx)
    assert invoke_idx > jobs_idx
    invoke_block = cfg[invoke_idx:].split("- match:")[0]
    assert 'substitution: "/invoke"' in invoke_block
    assert "(?!" not in cfg
