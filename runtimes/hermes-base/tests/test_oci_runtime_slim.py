"""OCI runtime-slim policy tests (TDD)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts" / "hermes"
PRUNE_VENDOR_PACKAGES = ("gateway", "tui_gateway", "acp_adapter")
PRUNE_SITE_PACKAGES = ("gateway", "tui_gateway", "acp_adapter")
FORBIDDEN_SNIPPET = "RUN pip install hermes-agent[all]"


def _script(name: str) -> Path:
    path = SCRIPTS / name
    assert path.is_file(), f"missing script: {path}"
    return path


def test_install_policy_script_passes() -> None:
    result = subprocess.run(
        ["bash", str(_script("check-hermes-install-policy.sh"))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_policy_rejects_forbidden_extra(tmp_path: Path) -> None:
    docker_dir = tmp_path / "runtimes" / "hermes-base"
    docker_dir.mkdir(parents=True)
    bad = docker_dir / "Dockerfile"
    bad.write_text(f"{FORBIDDEN_SNIPPET}\n", encoding="utf-8")
    env = {**os.environ, "HERMES_POLICY_ROOT": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(_script("check-hermes-install-policy.sh"))],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "forbidden" in (result.stdout + result.stderr).lower()


def test_prune_removes_runtime_fat_packages(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    for pkg in PRUNE_SITE_PACKAGES:
        (site / pkg).mkdir()
        (site / pkg / "__init__.py").write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(_script("prune-hermes-packages.sh")), str(site)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for pkg in PRUNE_SITE_PACKAGES:
        assert not (site / pkg).exists(), f"{pkg} should be pruned"


def test_prune_vendor_keeps_hermes_cli(tmp_path: Path) -> None:
    vendor = tmp_path / "src"
    vendor.mkdir()
    for pkg in (*PRUNE_VENDOR_PACKAGES, "hermes_cli"):
        (vendor / pkg).mkdir()

    env = {**os.environ, "HERMES_VENDOR_SRC": str(vendor), "HERMES_PRUNE_SITE": "0"}
    result = subprocess.run(
        ["bash", str(_script("prune-hermes-packages.sh"))],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (vendor / "hermes_cli").is_dir()
    for pkg in PRUNE_VENDOR_PACKAGES:
        assert not (vendor / pkg).exists(), f"vendor/{pkg} should be pruned"


def test_dockerfile_uses_prune_and_editable_install() -> None:
    dockerfile = ROOT / "runtimes" / "hermes-base" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert "prune-hermes-packages.sh" in text
    assert "uv pip install -e ./vendor/hermes-agent/src" in text
    assert "hermes-agent[all]" not in text
    assert "hermes-agent[gateway]" not in text


def test_image_size_script_rejects_oversized() -> None:
    env = {
        **os.environ,
        "HERMES_IMAGE_MAX_MIB": "1",
        "HERMES_IMAGE_SIZE_BYTES": "2097152",
    }
    result = subprocess.run(
        ["bash", str(_script("check-hermes-image-size.sh")), "hermes-base:fake"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "exceeds" in (result.stdout + result.stderr).lower()
