"""FastMCP infra providers.

Reads ``cfg["fastmcp"]`` (validated against ``FastMcpSourceConfig``) and
exposes helpers for the bundle factory:

  - ``build_server_kwargs``  → kwargs to splat into ``FastMCP(...)``
  - ``apply_task_queue_env`` → sets FASTMCP_DOCKET__* env vars before construction
"""

from __future__ import annotations

import os
from typing import Any

from runtime_common.secrets import SecretResolver


def _section(cfg: dict) -> dict:
    return cfg.get("fastmcp") or {}


def build_server_kwargs(cfg: dict, secrets: SecretResolver) -> dict[str, Any]:
    """Map ``cfg.fastmcp`` to keyword arguments for the FastMCP constructor.

    Excludes infrastructure that must be wired via env vars (task queue) — call
    ``apply_task_queue_env(cfg, secrets)`` separately for that.
    """
    section = _section(cfg)
    kwargs: dict[str, Any] = {
        "strict_input_validation": bool(section.get("strict_input_validation", False)),
        "mask_error_details": bool(section.get("mask_error_details", False)),
    }
    if section.get("list_page_size") is not None:
        kwargs["list_page_size"] = int(section["list_page_size"])

    session_state_store_backend = section.get("session_state_store", "memory")
    if session_state_store_backend != "memory":
        store = _build_session_state_store(session_state_store_backend, secrets)
        if store is not None:
            kwargs["session_state_store"] = store

    return kwargs


def _build_session_state_store(backend: str, secrets: SecretResolver) -> Any | None:
    if backend == "redis":
        try:
            from key_value.aio.stores.redis import RedisStore  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "session_state_store='redis' requires the 'py-key-value-aio[redis]' package"
            ) from exc
        return RedisStore.from_url(secrets.resolve("SESSION_REDIS_DSN"))
    raise ValueError(f"unsupported session_state_store: {backend!r}")


def apply_task_queue_env(cfg: dict, secrets: SecretResolver) -> None:
    """Translate ``cfg.fastmcp.task_queue`` and ``task_concurrency`` into FASTMCP_DOCKET__* env vars.

    FastMCP/Docket reads these at FastMCP() construction time, so call this
    *before* instantiating ``FastMCP(...)``.
    """
    section = _section(cfg)
    backend = section.get("task_queue", "memory")
    concurrency = int(section.get("task_concurrency", 10))

    if backend == "memory":
        os.environ["FASTMCP_DOCKET__URL"] = "memory://"
    elif backend in ("redis", "valkey"):
        os.environ["FASTMCP_DOCKET__URL"] = secrets.resolve("TASK_REDIS_DSN")
    else:
        raise ValueError(f"unsupported task_queue: {backend!r}")

    os.environ["FASTMCP_DOCKET__CONCURRENCY"] = str(concurrency)
