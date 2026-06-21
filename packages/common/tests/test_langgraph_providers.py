"""Tests for runtime_common.providers.langgraph."""

from unittest.mock import MagicMock

import pytest

from runtime_common.providers import langgraph as lg
from runtime_common.providers import pg_infra


class _MapSecretResolver:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def resolve(self, ref: str) -> str:
        if ref not in self._values:
            raise KeyError(ref)
        return self._values[ref]


@pytest.fixture(autouse=True)
def _reset_pg_registry():
    pg_infra.reset_registry()
    yield
    pg_infra.reset_registry()


def test_build_checkpointer_default_is_postgres_and_uses_shared():
    shared = MagicMock()
    pg_infra.set_shared_checkpointer(shared)
    result = lg.build_checkpointer({}, _MapSecretResolver())
    assert result is shared


def test_build_checkpointer_none_opt_out():
    result = lg.build_checkpointer(
        {"langgraph": {"checkpointer": "none"}},
        _MapSecretResolver(),
    )
    assert result is None


def test_build_checkpointer_memory():
    pytest.importorskip("langgraph")
    result = lg.build_checkpointer(
        {"langgraph": {"checkpointer": "memory"}},
        _MapSecretResolver(),
    )
    assert result is not None


def test_build_checkpointer_postgres_requires_registry():
    with pytest.raises(RuntimeError, match="not initialized"):
        lg.build_checkpointer(
            {"langgraph": {"checkpointer": "postgres"}},
            _MapSecretResolver({"CHECKPOINTER_DSN": "postgresql://x"}),
        )
