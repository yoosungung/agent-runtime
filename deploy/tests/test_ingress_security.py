"""Ingress must not expose unauthenticated deploy-api or MCP discovery paths."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_INGRESS_PATHS = (
    "path: /v1/source-meta",
    "path: /v1/user-meta",
    "path: /v1/mcp/servers",
    "path: /v1/mcp/stream",
)

REQUIRED_INGRESS_PATHS = (
    "path: /v1/agents/",
    "path: /v1/mcp/invoke",
    "path: /",
)


def _kustomize_build(path: Path) -> str:
    return subprocess.check_output(
        ["kubectl", "kustomize", str(path)],
        text=True,
    )


def _ingress_documents(manifest: str) -> str:
    chunks: list[str] = []
    for doc in manifest.split("---"):
        if "kind: Ingress" in doc and "name: agents-runtime" in doc:
            chunks.append(doc)
    return "\n".join(chunks)


def test_base_ingress_blocks_public_bundles_and_debug_paths() -> None:
    manifest = _ingress_documents(_kustomize_build(REPO_ROOT / "deploy/k8s/base"))
    for forbidden in FORBIDDEN_INGRESS_PATHS:
        assert forbidden not in manifest, forbidden
    for required in REQUIRED_INGRESS_PATHS:
        assert required in manifest, required
    assert "server-snippet" not in manifest
    assert "proxy-body-size: 256m" in manifest


def test_dev_overlay_inherits_hardened_ingress() -> None:
    manifest = _ingress_documents(_kustomize_build(REPO_ROOT / "deploy/k8s/overlays/dev"))
    for forbidden in FORBIDDEN_INGRESS_PATHS:
        assert forbidden not in manifest, forbidden
    assert "host: agents.k8s-test" in manifest


def test_stage_and_prod_overlays_inherit_hardened_ingress() -> None:
    for overlay in ("stage", "prod"):
        manifest = _ingress_documents(
            _kustomize_build(REPO_ROOT / f"deploy/k8s/overlays/{overlay}")
        )
        for forbidden in FORBIDDEN_INGRESS_PATHS:
            assert forbidden not in manifest, f"{overlay}: {forbidden}"
        assert "host: agents.didim365.app" in manifest


def test_deploy_api_network_policy_has_no_ingress_nginx_rule() -> None:
    manifest = _kustomize_build(REPO_ROOT / "deploy/k8s/base")
    assert "ingress-nginx" not in manifest.split("name: deploy-api-ingress")[1].split("---")[0]
