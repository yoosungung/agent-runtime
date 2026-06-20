"""Shared loader fixture for bundle tests.

Each bundle has its own ``app.py``. They can't be imported by name since
they collide, so each test loads its target through importlib under a
unique synthetic module name. Exposed as the ``load_bundle`` fixture
because under ``--import-mode=importlib`` conftest isn't itself importable.

Search order for ``rel_path`` (e.g. ``mcp-base/fastmcp_bundle``,
``mcp/email_bundle``):

1. ``deploy/examples/<rel_path>/app.py`` — tutorial samples
2. ``bundles/<rel_path>/app.py`` — production bundles
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = EXAMPLES_DIR.parent.parent
BUNDLES_DIR = REPO_ROOT / "bundles"


def resolve_bundle_app(rel_path: str) -> Path:
    for base in (EXAMPLES_DIR, BUNDLES_DIR):
        path = base / rel_path / "app.py"
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"no app.py for bundle {rel_path!r} under {EXAMPLES_DIR} or {BUNDLES_DIR}"
    )


def _evict_bundle_local_modules() -> None:
    """Drop bundle-local modules left by a prior bundle load."""
    for name in list(sys.modules):
        if name in ("models", "utils", "client") or name.startswith("providers"):
            del sys.modules[name]


@pytest.fixture
def load_bundle() -> Callable[[str, str], ModuleType]:
    def _load(rel_path: str, alias: str) -> ModuleType:
        _evict_bundle_local_modules()
        path = resolve_bundle_app(rel_path)
        spec = importlib.util.spec_from_file_location(alias, path)
        assert spec and spec.loader, f"failed to spec {path}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
        return module

    return _load
