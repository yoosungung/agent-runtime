"""Tests for thread history message parsing helpers."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import MemorySaver

from runtime_common.providers import pg_infra
from runtime_common.thread_history.adk import _role_from_adk_event, _text_from_adk_event
from runtime_common.thread_history.base import UiMessage
from runtime_common.thread_history.langgraph import LangGraphThreadHistoryAdapter


def test_adk_event_text_and_role_from_content() -> None:
    event = {
        "content": {
            "role": "user",
            "parts": [{"text": "Hello"}],
        }
    }
    assert _role_from_adk_event(event) == "user"
    assert _text_from_adk_event(event) == "Hello"


def test_adk_event_model_role_maps_to_assistant() -> None:
    event = {
        "content": {
            "role": "model",
            "parts": [{"text": "Hi there"}],
        }
    }
    assert _role_from_adk_event(event) == "assistant"
    assert _text_from_adk_event(event) == "Hi there"


@pytest.mark.asyncio
async def test_langgraph_hydrate_skips_empty_tool_call_ai_messages() -> None:
    pg_infra.reset_registry()
    saver = MemorySaver()
    pg_infra.set_shared_checkpointer(saver)

    session_id = "sess-tool-rounds"
    config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {
        "messages": [
            HumanMessage(content="wiki 찾아줘"),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {}, "id": "1", "type": "tool_call"}],
            ),
            ToolMessage(content="file body", tool_call_id="1"),
            AIMessage(content="최종 답변"),
        ],
    }
    checkpoint["channel_versions"] = {"messages": 1}
    await saver.aput(config, checkpoint, {}, {"messages": 1})

    try:
        adapter = LangGraphThreadHistoryAdapter()
        messages = await adapter.load_messages(
            provider_session_id=session_id,
            provider_meta={},
        )
        assert messages == [
            UiMessage(role="user", content="wiki 찾아줘"),
            UiMessage(role="assistant", content="최종 답변"),
        ]
    finally:
        pg_infra.reset_registry()
