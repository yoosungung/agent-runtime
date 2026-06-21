"""Shared Postgres infra for agent pool pods (checkpointer + ADK sessions).

Pod lifespan calls ``init_checkpointer`` once; bundle factories resolve the shared
``AsyncPostgresSaver`` via ``build_checkpointer`` when ``checkpointer=postgres``.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime_common.providers.adk import build_session_service
from runtime_common.secrets import SecretResolver

logger = logging.getLogger(__name__)

_shared_checkpointer: Any | None = None
_checkpointer_pool: Any | None = None


def _normalize_pg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def reset_registry() -> None:
    """Clear module-level singletons (tests)."""
    global _shared_checkpointer, _checkpointer_pool  # noqa: PLW0603
    _shared_checkpointer = None
    _checkpointer_pool = None


def set_shared_checkpointer(checkpointer: Any, pool: Any | None = None) -> None:
    global _shared_checkpointer, _checkpointer_pool  # noqa: PLW0603
    _shared_checkpointer = checkpointer
    _checkpointer_pool = pool


def get_shared_checkpointer() -> Any:
    if _shared_checkpointer is None:
        raise RuntimeError("postgres checkpointer not initialized — call init_checkpointer() at startup")
    return _shared_checkpointer


async def init_checkpointer(dsn: str, *, pgbouncer: bool = False) -> Any:
    """Create a shared AsyncPostgresSaver + connection pool and run ``setup()`` once."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    global _shared_checkpointer, _checkpointer_pool  # noqa: PLW0603

    clean_dsn = _normalize_pg_dsn(dsn)
    conn_kwargs: dict[str, Any] = {"autocommit": True, "row_factory": dict_row}
    if pgbouncer:
        conn_kwargs["prepare_threshold"] = None

    async def _pool_check(conn: Any) -> None:
        await conn.execute("SELECT 1")

    pool = AsyncConnectionPool(
        conninfo=clean_dsn,
        min_size=1,
        max_size=10,
        kwargs=conn_kwargs,
        check=_pool_check,
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    _shared_checkpointer = checkpointer
    _checkpointer_pool = pool
    logger.info("checkpointer_initialized", extra={"pgbouncer": pgbouncer})
    return checkpointer


async def close_checkpointer() -> None:
    """Release the shared checkpointer pool (lifespan shutdown)."""
    global _shared_checkpointer, _checkpointer_pool  # noqa: PLW0603
    pool = _checkpointer_pool
    _shared_checkpointer = None
    _checkpointer_pool = None
    if pool is not None:
        await pool.close()


def _adk_session_cache_key(cfg: dict, secrets: SecretResolver) -> str:
    section = cfg.get("adk") or {}
    backend = section.get("session_service", "database")
    if backend == "memory":
        return "memory"
    if backend == "vertexai":
        return "vertexai"
    return f"database:{secrets.resolve('SESSION_DB_DSN')}"


def get_adk_session_service(
    cfg: dict,
    secrets: SecretResolver,
    cache: dict[str, Any],
) -> Any:
    """Return a cached ADK session service for ``cfg.adk.session_service``."""
    key = _adk_session_cache_key(cfg, secrets)
    if key not in cache:
        cache[key] = build_session_service(cfg, secrets)
    return cache[key]
