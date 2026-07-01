"""Hermes SSE streaming unit tests (TDD)."""

from __future__ import annotations

import pytest

from hermes_base.hermes_stream import stream_run_conversation


@pytest.mark.asyncio()
async def test_stream_emits_text_deltas_and_done() -> None:
    def run_fn(on_delta) -> dict:
        on_delta("Hel")
        on_delta("lo")
        return {"final_response": "Hello"}

    chunks: list[str] = []
    async for chunk in stream_run_conversation(run_fn, timeout=5.0):
        chunks.append(chunk)

    body = "".join(chunks)
    assert '"text": "Hel"' in body or '"text":"Hel"' in body
    assert '"text": "lo"' in body or '"text":"lo"' in body
    assert "data: [DONE]" in body


@pytest.mark.asyncio()
async def test_stream_ignores_none_delta() -> None:
    def run_fn(on_delta) -> dict:
        on_delta("A")
        on_delta(None)
        on_delta("B")
        return {"final_response": "AB"}

    body = "".join([c async for c in stream_run_conversation(run_fn, timeout=5.0)])
    assert '"text": "A"' in body or '"text":"A"' in body
    assert '"text": "B"' in body or '"text":"B"' in body
    assert "data: [DONE]" in body


@pytest.mark.asyncio()
async def test_stream_emits_output_when_no_deltas() -> None:
    def run_fn(_on_delta) -> dict:
        return {"final_response": "only final"}

    body = "".join([c async for c in stream_run_conversation(run_fn, timeout=5.0)])
    assert '"output": "only final"' in body or '"output":"only final"' in body
    assert "data: [DONE]" in body


@pytest.mark.asyncio()
async def test_stream_reports_errors() -> None:
    def run_fn(_on_delta) -> dict:
        raise RuntimeError("boom")

    body = "".join([c async for c in stream_run_conversation(run_fn, timeout=5.0)])
    assert "boom" in body
    assert "[DONE]" not in body


@pytest.mark.asyncio()
async def test_stream_callback_wiring_with_mock_agent() -> None:
    calls: list[str] = []

    def run_conversation(**kwargs: object) -> dict:
        cb = kwargs.get("stream_callback")
        assert cb is not None
        cb("tok")
        calls.append("ran")
        return {"final_response": "tok"}

    def run_fn(on_delta) -> dict:
        return run_conversation(user_message="hi", stream_callback=on_delta)

    body = "".join([c async for c in stream_run_conversation(run_fn, timeout=5.0)])
    assert "tok" in body
    assert calls == ["ran"]
