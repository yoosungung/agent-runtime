"""Tests for thread history message parsing helpers."""

from __future__ import annotations

from runtime_common.thread_history.adk import _role_from_adk_event, _text_from_adk_event


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
