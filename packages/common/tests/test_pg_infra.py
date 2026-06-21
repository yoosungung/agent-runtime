"""Tests for runtime_common.providers.pg_infra registry helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime_common.providers import pg_infra


class _MapSecretResolver:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def resolve(self, ref: str) -> str:
        if ref not in self._values:
            raise KeyError(ref)
        return self._values[ref]


@pytest.fixture(autouse=True)
def _reset_pg_registry():
    pg_infra.reset_registry()
    yield
    pg_infra.reset_registry()


def test_get_shared_checkpointer_raises_when_uninitialized():
    with pytest.raises(RuntimeError, match="not initialized"):
        pg_infra.get_shared_checkpointer()


def test_set_shared_checkpointer():
    saver = object()
    pg_infra.set_shared_checkpointer(saver)
    assert pg_infra.get_shared_checkpointer() is saver


def test_get_adk_session_service_caches_by_backend_and_dsn(monkeypatch):
    created: list[str] = []

    class FakeDatabaseSessionService:
        def __init__(self, db_url: str) -> None:
            created.append(db_url)

    monkeypatch.setattr(
        "runtime_common.providers.pg_infra.build_session_service",
        lambda cfg, secrets: FakeDatabaseSessionService(secrets.resolve("SESSION_DB_DSN")),
    )

    cfg = {"adk": {"session_service": "database"}}
    secrets = _MapSecretResolver({"SESSION_DB_DSN": "postgresql://u:p@localhost/db"})
    cache: dict = {}

    svc1 = pg_infra.get_adk_session_service(cfg, secrets, cache)
    svc2 = pg_infra.get_adk_session_service(cfg, secrets, cache)

    assert svc1 is svc2
    assert created == ["postgresql://u:p@localhost/db"]


def test_get_adk_session_service_defaults_to_database_dsn(monkeypatch):
    created: list[str] = []

    class FakeDatabaseSessionService:
        def __init__(self, db_url: str) -> None:
            created.append(db_url)

    monkeypatch.setattr(
        "runtime_common.providers.pg_infra.build_session_service",
        lambda cfg, secrets: FakeDatabaseSessionService(secrets.resolve("SESSION_DB_DSN")),
    )

    secrets = _MapSecretResolver({"SESSION_DB_DSN": "postgresql://u:p@localhost/db"})
    cache: dict = {}

    pg_infra.get_adk_session_service({}, secrets, cache)

    assert created == ["postgresql://u:p@localhost/db"]


@pytest.mark.asyncio
async def test_init_checkpointer_sets_registry():
    mock_saver = MagicMock()
    mock_saver.setup = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.open = AsyncMock()
    mock_pool.close = AsyncMock()

    with (
        patch("psycopg_pool.AsyncConnectionPool", return_value=mock_pool),
        patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver",
            return_value=mock_saver,
        ),
    ):
        await pg_infra.init_checkpointer(
            "postgresql://u:p@localhost/db",
            pgbouncer=True,
        )

    assert pg_infra.get_shared_checkpointer() is mock_saver
    mock_saver.setup.assert_awaited_once()
    mock_pool.open.assert_awaited_once()
