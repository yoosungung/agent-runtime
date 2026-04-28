"""Shared loader fixture for example bundle tests.

Each bundle has its own ``app.py``. They can't be imported by name since
they collide, so each test loads its target through importlib under a
unique synthetic module name. Exposed as the ``load_bundle`` fixture
because under ``--import-mode=importlib`` conftest isn't itself importable.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def load_bundle() -> Callable[[str, str], ModuleType]:
    def _load(rel_path: str, alias: str) -> ModuleType:
        path = EXAMPLES_DIR / rel_path / "app.py"
        spec = importlib.util.spec_from_file_location(alias, path)
        assert spec and spec.loader, f"failed to spec {path}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        spec.loader.exec_module(module)
        return module

    return _load
