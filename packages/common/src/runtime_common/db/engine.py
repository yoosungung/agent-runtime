from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _strip_sslmode(dsn: str) -> tuple[str, str | None]:
    """Remove sslmode from DSN query string; return (clean_dsn, sslmode_value)."""
    parsed = urlparse(dsn)
    params = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = params.pop("sslmode", [None])[0]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    clean = urlunparse(parsed._replace(query=new_query))
    return clean, sslmode


def make_engine(dsn: str, *, pgbouncer: bool = False) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Pass ``pgbouncer=True`` when the DSN targets a PgBouncer in transaction
    mode.  This disables asyncpg's prepared-statement cache (which is
    incompatible with transaction-mode pooling) and keeps the SQLAlchemy-side
    pool small so PgBouncer owns the connection fan-out.
    """
    dsn, sslmode = _strip_sslmode(dsn)
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    connect_args: dict[str, Any] = {"timeout": 30}

    if sslmode == "disable":
        connect_args["ssl"] = False

    if pgbouncer:
        connect_args["statement_cache_size"] = 0
        kwargs["pool_size"] = 3
        kwargs["max_overflow"] = 2

    if connect_args:
        kwargs["connect_args"] = connect_args

    return create_async_engine(dsn, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
