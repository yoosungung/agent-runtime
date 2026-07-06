"""Kustomize smoke tests for embedded Garage bundle storage."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _kustomize_build(path: Path) -> str:
    return subprocess.check_output(
        ["kubectl", "kustomize", str(path)],
        text=True,
    )


def test_garage_kustomize_builds_in_runtime_namespace() -> None:
    manifest = _kustomize_build(REPO_ROOT / "deploy/k8s/garage")
    assert "namespace: runtime" in manifest
    assert "namespace: garage" not in manifest
    assert "name: garage-s3" in manifest
    assert "dxflrs/garage:v2.3.0" in manifest
    assert "kind: Namespace" not in manifest


def test_dev_overlay_includes_garage() -> None:
    manifest = _kustomize_build(REPO_ROOT / "deploy/k8s/overlays/dev")
    assert "namespace: runtime" in manifest
    assert "name: s3-creds" in manifest
    assert "name: garage-s3" in manifest
    assert "garage-headless.runtime.svc.cluster.local" in manifest
    assert "kind: StatefulSet" in manifest
    assert "name: garage" in manifest


def test_dev_overlay_uses_immutable_image_tags() -> None:
    manifest = _kustomize_build(REPO_ROOT / "deploy/k8s/overlays/dev")
    assert "ghcr.io/yoosungung/agent-runtime/backend:__IMAGE_TAG__" in manifest
    assert "agents-runtime/backend:latest" not in manifest
    assert "imagePullPolicy: IfNotPresent" in manifest
    assert "imagePullPolicy: Always" not in manifest


def test_makefile_applies_garage_via_overlay() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "k8s-apply-garage" in makefile
    assert "k8s-apply-dev: ensure-jwt-secret ensure-registry-secret k8s-apply-garage" not in makefile


def test_base_kustomization_has_s3_secret() -> None:
    kustomization = (REPO_ROOT / "deploy/k8s/base/kustomization.yaml").read_text()
    assert "s3-creds" in kustomization
    assert "s3-creds.env" in kustomization
    assert "../garage" in kustomization


def test_migration_job_includes_vfs_sql() -> None:
    migration_job = (REPO_ROOT / "deploy/k8s/base/migration-job.yaml").read_text()
    assert "0002_vfs.sql:" in migration_job
    assert "vfs_agent_files" in migration_job
    assert "0013_vfs_wiki.sql:" in migration_job
    assert "vfs_wiki_files" in migration_job
    assert "0014_resource_visibility_allowlist.sql:" in migration_job
    assert "0014_resource_visibility_allowlist.sql" in migration_job.split("command:")[1]
    assert 'migration-version: "0014"' in migration_job
    assert "name: db-migrate-0014" in migration_job
    assert "app: db-migrate" in migration_job


def test_backend_uses_s3_creds_secret() -> None:
    backend = (REPO_ROOT / "deploy/k8s/base/backend.yaml").read_text()
    assert "name: s3-creds" in backend
    assert "backend-bundle-pvc" not in backend
