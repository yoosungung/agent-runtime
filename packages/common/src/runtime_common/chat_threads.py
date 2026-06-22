"""Chat thread registry helpers — thread_type derivation and provider metadata."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from runtime_common.schemas import parse_runtime_pool


class ChatThreadType(StrEnum):
    LANGGRAPH = "langgraph"
    ADK = "adk"
    CUSTOM = "custom"


def thread_type_from_runtime_pool(runtime_pool: str) -> ChatThreadType:
    """Map ``source_meta.runtime_pool`` to a chat thread provider type."""
    parsed = parse_runtime_pool(runtime_pool)
    if parsed.kind != "agent":
        raise ValueError(f"chat threads require agent runtime_pool, got {runtime_pool!r}")
    if parsed.runtime_kind == "compiled_graph":
        return ChatThreadType.LANGGRAPH
    if parsed.runtime_kind == "adk":
        return ChatThreadType.ADK
    if parsed.runtime_kind == "custom":
        return ChatThreadType.CUSTOM
    raise ValueError(f"unsupported agent runtime_pool for chat threads: {runtime_pool!r}")


def build_provider_meta(
    thread_type: ChatThreadType,
    *,
    principal_user_id: int | str,
) -> dict[str, Any]:
    """Build provider-specific lookup hints stored on ``chat_threads.provider_meta``."""
    if thread_type == ChatThreadType.ADK:
        return {"app_name": "agent-base", "adk_user_id": str(principal_user_id)}
    return {}
