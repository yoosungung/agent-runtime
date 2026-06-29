"""Request-scoped HERMES_HOME for multi-profile pool pods."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_active_home: ContextVar[Path | None] = ContextVar("hermes_active_home", default=None)


def get_active_home() -> Path | None:
    return _active_home.get()


@contextmanager
def profile_runtime_scope(home: Path) -> Iterator[Path]:
    """Set HERMES_HOME for the current asyncio task / thread."""
    token = _active_home.set(home.resolve())
    prev = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(home.resolve())
    try:
        yield home
    finally:
        _active_home.reset(token)
        if prev is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = prev
