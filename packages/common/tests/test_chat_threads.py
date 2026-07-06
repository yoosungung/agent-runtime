"""Tests for chat thread registry helpers."""

from __future__ import annotations

import pytest

from runtime_common.chat_threads import (
    ChatThreadType,
    build_provider_meta,
    thread_type_from_runtime_pool,
)


@pytest.mark.parametrize(
    ("runtime_pool", "expected"),
    [
        ("agent:compiled_graph", ChatThreadType.LANGGRAPH),
        ("agent:adk", ChatThreadType.ADK),
        ("agent:custom:my-bot", ChatThreadType.CUSTOM),
        ("agent:hermes", ChatThreadType.HERMES),
    ],
)
def test_thread_type_from_runtime_pool(runtime_pool: str, expected: ChatThreadType) -> None:
    assert thread_type_from_runtime_pool(runtime_pool) == expected


def test_thread_type_rejects_non_agent() -> None:
    with pytest.raises(ValueError, match="agent runtime_pool"):
        thread_type_from_runtime_pool("mcp:fastmcp")


def test_build_provider_meta_adk() -> None:
    meta = build_provider_meta(ChatThreadType.ADK, principal_user_id=42)
    assert meta == {"app_name": "agent-base", "adk_user_id": "42"}


def test_build_provider_meta_langgraph_empty() -> None:
    assert build_provider_meta(ChatThreadType.LANGGRAPH, principal_user_id=1) == {}
