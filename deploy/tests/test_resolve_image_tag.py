"""IMAGE_TAG short-SHA resolution (GHCR tags full git SHA)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "resolve-image-tag.sh"


@pytest.fixture(scope="module")
def head_full() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


@pytest.fixture(scope="module")
def head_short7(head_full: str) -> str:
    return head_full[:7]


def _resolve(tag: str) -> str:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    return subprocess.check_output(
        ["bash", str(SCRIPT), tag], cwd=REPO_ROOT, text=True
    ).strip()


def test_resolve_image_tag_script_exists() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "resolve-image-tag.sh must be executable"


def test_full_sha_passthrough(head_full: str) -> None:
    assert _resolve(head_full) == head_full


def test_short_sha_expands_to_full(head_full: str, head_short7: str) -> None:
    assert _resolve(head_short7) == head_full


def test_non_git_tag_passthrough() -> None:
    custom = "admin-spa-0582a41"
    assert _resolve(custom) == custom
