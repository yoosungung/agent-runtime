"""LangGraph / DeepAgents infra providers.

Reads ``cfg["langgraph"]`` (validated against ``LangGraphSourceConfig``) and
materialises the framework-native checkpointer / store / cache objects, pulling
DSNs and credentials from the bundle's ``SecretResolver``.

Bundle authors should call these inside their factory and pass the returned
objects to ``builder.compile(...)`` or ``create_deep_agent(...)``.
"""

from __future__ import annotations

from typing import Any

from runtime_common.secrets import SecretResolver


def _section(cfg: dict) -> dict:
    return cfg.get("langgraph") or {}


def get_recursion_limit(cfg: dict) -> int:
    """Return the configured recursion limit (default 100)."""
    return int(_section(cfg).get("recursion_limit", 100))


def get_model_spec(cfg: dict) -> str | None:
    """Return ``cfg.langgraph.model`` (used by DeepAgents)."""
    return _section(cfg).get("model")


def build_checkpointer(cfg: dict, secrets: SecretResolver) -> Any | None:
    """Build a LangGraph checkpointer based on ``cfg.langgraph.checkpointer``.

    Returns ``None`` when ``checkpointer == "none"``. DSN is resolved from
    ``secrets["CHECKPOINTER_DSN"]`` for backends that need one.
    """
    backend = _section(cfg).get("checkpointer", "none")
    if backend == "none":
        return None
    if backend == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if backend == "redis":
        # runtime_common already ships a RedisSaver factory used by the registry.
        from runtime_common.registry import make_redis_saver

        return make_redis_saver(secrets.resolve("CHECKPOINTER_DSN"))
    if backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver.from_conn_string(secrets.resolve("CHECKPOINTER_DSN"))
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        return AsyncSqliteSaver.from_conn_string(secrets.resolve("CHECKPOINTER_DSN"))
    if backend == "mongo":
        from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

        return AsyncMongoDBSaver.from_conn_string(secrets.resolve("CHECKPOINTER_DSN"))
    raise ValueError(f"unsupported checkpointer backend: {backend!r}")


def build_store(cfg: dict, secrets: SecretResolver) -> Any | None:
    """Build a LangGraph store from ``cfg.langgraph.store``.

    Returns ``None`` when ``backend == "none"``. ``store.index`` enables
    semantic search when ``embed`` is set.
    """
    section = _section(cfg).get("store") or {}
    backend = section.get("backend", "none")
    if backend == "none":
        return None

    index = section.get("index") or {}
    index_kwargs = {}
    if index.get("embed"):
        index_kwargs = {"index": {"embed": index["embed"], "dims": index.get("dims") or 1536}}

    if backend == "memory":
        from langgraph.store.memory import InMemoryStore

        return InMemoryStore(**index_kwargs)
    if backend == "postgres":
        from langgraph.store.postgres.aio import AsyncPostgresStore

        return AsyncPostgresStore.from_conn_string(secrets.resolve("STORE_DSN"), **index_kwargs)
    if backend == "redis":
        # Optional dep; raise informatively rather than crashing on import.
        try:
            from langgraph.store.redis.aio import AsyncRedisStore  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "store backend 'redis' requires the 'langgraph-store-redis' package"
            ) from exc
        return AsyncRedisStore.from_conn_string(secrets.resolve("STORE_DSN"), **index_kwargs)
    raise ValueError(f"unsupported store backend: {backend!r}")


def build_cache(cfg: dict, secrets: SecretResolver) -> Any | None:
    """Build a LangGraph node-result cache from ``cfg.langgraph.cache``.

    Returns ``None`` when ``cache == "none"``.
    """
    backend = _section(cfg).get("cache", "none")
    if backend == "none":
        return None
    if backend == "memory":
        from langgraph.cache.memory import InMemoryCache

        return InMemoryCache()
    if backend == "sqlite":
        from langgraph.cache.sqlite import SqliteCache  # type: ignore[import-not-found]

        return SqliteCache(secrets.resolve("CACHE_DSN"))
    if backend == "redis":
        from langgraph.cache.redis import RedisCache  # type: ignore[import-not-found]

        return RedisCache(secrets.resolve("CACHE_DSN"))
    raise ValueError(f"unsupported cache backend: {backend!r}")
