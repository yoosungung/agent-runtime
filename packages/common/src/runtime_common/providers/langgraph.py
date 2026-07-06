"""LangGraph / DeepAgents infra providers.

Reads ``cfg["langgraph"]`` (validated against ``LangGraphSourceConfig``) and
materialises the framework-native checkpointer / store / cache objects, pulling
DSNs and credentials from the bundle's ``SecretResolver``.

Bundle authors should call these inside their factory and pass the returned
objects to ``builder.compile(...)`` or ``create_deep_agent(...)``.
"""

from __future__ import annotations

import os
from typing import Any

from runtime_common.secrets import SecretResolver

DEFAULT_LLM_MODEL_SPEC = "anthropic:claude-sonnet-4-6"

_LLM_CFG_KEY_TO_ENV = (
    ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    ("openai_api_key", "OPENAI_API_KEY"),
    ("google_api_key", "GOOGLE_API_KEY"),
)


def _section(cfg: dict) -> dict:
    return cfg.get("langgraph") or {}


def get_recursion_limit(cfg: dict) -> int:
    """Return the configured recursion limit (default 100)."""
    return int(_section(cfg).get("recursion_limit", 100))


def get_model_spec(cfg: dict) -> str | None:
    """Return ``cfg.langgraph.model`` (used by DeepAgents)."""
    return _section(cfg).get("model")


def extract_preset_name(model_spec: str | None) -> str | None:
    """Return preset name from ``preset:NAME`` model spec."""
    if model_spec and model_spec.startswith("preset:"):
        name = model_spec[len("preset:") :].strip()
        return name or None
    return None


def read_llm_preset_limits(preset_name: str) -> tuple[int | None, int | None]:
    """Read reconciler-injected context limits for a named LLM preset."""
    prefix = f"LLM_PRESET_{preset_name}"
    ctx_raw = os.environ.get(f"{prefix}_CONTEXT_WINDOW", "").strip()
    out_raw = os.environ.get(f"{prefix}_MAX_OUTPUT_TOKENS", "").strip()
    context = int(ctx_raw) if ctx_raw else None
    max_output = int(out_raw) if out_raw else None
    return context, max_output


def export_llm_api_keys(cfg: dict) -> None:
    """Copy provider API keys from merged cfg into process env for init_chat_model."""
    for cfg_key, env_key in _LLM_CFG_KEY_TO_ENV:
        if val := cfg.get(cfg_key):
            os.environ[env_key] = val

    # Support preset dynamic mapping (langgraph, adk, hermes config sections)
    model_spec = (
        cfg.get("langgraph", {}).get("model")
        or cfg.get("adk", {}).get("model")
        or cfg.get("hermes", {}).get("model")
    )
    if model_spec and model_spec.startswith("preset:"):
        preset_name = model_spec[len("preset:"):].strip()
        api_key = os.environ.get(f"LLM_PRESET_{preset_name}_API_KEY", "").strip()
        api_base = os.environ.get(f"LLM_PRESET_{preset_name}_API_BASE", "").strip()
        mode = os.environ.get(f"LLM_PRESET_{preset_name}_MODE", "").strip()
        provider = os.environ.get(f"LLM_PRESET_{preset_name}_PROVIDER", "openai").strip()

        if api_key:
            if mode == "openai_compatible":
                os.environ["OPENAI_API_KEY"] = api_key
            else:
                if provider == "openai":
                    os.environ["OPENAI_API_KEY"] = api_key
                elif provider == "anthropic":
                    os.environ["ANTHROPIC_API_KEY"] = api_key
                elif provider == "google":
                    os.environ["GOOGLE_API_KEY"] = api_key
                    os.environ["GEMINI_API_KEY"] = api_key
        if api_base:
            os.environ["OPENAI_API_BASE"] = api_base


def resolve_model_spec(cfg: dict) -> str:
    """Resolve DeepAgents/LangGraph model: cfg → platform env → repo default."""
    explicit = get_model_spec(cfg)
    if explicit:
        if explicit.startswith("preset:"):
            preset_name = explicit[len("preset:"):].strip()
            mode = os.environ.get(f"LLM_PRESET_{preset_name}_MODE", "").strip()
            model_id = os.environ.get(f"LLM_PRESET_{preset_name}_MODEL_ID", "").strip()
            provider = os.environ.get(f"LLM_PRESET_{preset_name}_PROVIDER", "openai").strip()
            if mode == "openai_compatible":
                return f"openai:{model_id}"
            return f"{provider}:{model_id}"
        return explicit
    platform = os.environ.get("DEFAULT_LLM_MODEL", "").strip()
    if platform:
        return platform
    return DEFAULT_LLM_MODEL_SPEC


def init_chat_model(spec: str, **kwargs: Any) -> Any:
    """Lazy wrapper so ``runtime-common`` tests can patch without langchain installed."""
    from langchain.chat_models import init_chat_model as _init_chat_model

    return _init_chat_model(spec, **kwargs)


def prepare_langgraph_llm(cfg: dict) -> str | Any:
    """Export cfg API keys and return the model for ``create_deep_agent``.

    ``openai:...`` specs are materialised with ``use_responses_api=False`` so
    OpenAI-compatible gateways that only implement Chat Completions work.
    Other providers are returned as string specs for deepagents to resolve.
    """
    export_llm_api_keys(cfg)
    spec = resolve_model_spec(cfg)
    if spec.startswith("openai:"):
        return init_chat_model(spec, use_responses_api=False)
    return spec


def build_checkpointer(cfg: dict, secrets: SecretResolver) -> Any | None:
    """Build a LangGraph checkpointer based on ``cfg.langgraph.checkpointer``.

    Returns ``None`` when ``checkpointer == "none"``. DSN is resolved from
    ``secrets["CHECKPOINTER_DSN"]`` for backends that need one.

    ``postgres`` uses the pod-level shared saver from ``pg_infra`` (initialized at
    agent-base lifespan). Other DSN backends are built per factory call.
    """
    backend = _section(cfg).get("checkpointer", "postgres")
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
        from runtime_common.providers.pg_infra import get_shared_checkpointer

        return get_shared_checkpointer()
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
