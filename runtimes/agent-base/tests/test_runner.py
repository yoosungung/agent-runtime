"""Unit tests for agent-base runner adapters."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_base.runner import run, run_stream
from runtime_common.schemas import AgentRuntimeKind


class TestRun:
    async def test_compiled_graph_ainvoke(self):
        instance = AsyncMock()
        instance.ainvoke.return_value = {"answer": "42"}
        result = await run(AgentRuntimeKind.COMPILED_GRAPH, instance, {"q": "?"}, "sess-1")
        assert result == {"output": {"answer": "42"}}
        instance.ainvoke.assert_called_once()
        # Verify session_id is threaded through as configurable.thread_id
        call_kwargs = instance.ainvoke.call_args
        assert call_kwargs.kwargs.get("config") == {"configurable": {"thread_id": "sess-1"}}

    async def test_compiled_graph_no_session(self):
        instance = AsyncMock()
        instance.ainvoke.return_value = {"result": "ok"}
        result = await run(AgentRuntimeKind.COMPILED_GRAPH, instance, {}, None)
        assert result == {"output": {"result": "ok"}}
        call_kwargs = instance.ainvoke.call_args
        assert call_kwargs.kwargs.get("config") is None

    async def test_custom_ainvoke(self):
        instance = AsyncMock()
        instance.ainvoke.return_value = "hello"
        result = await run(AgentRuntimeKind.CUSTOM, instance, {}, None)
        assert result == {"output": "hello"}

    async def test_custom_callable(self):
        async def my_fn(inp):
            return "result"

        result = await run(AgentRuntimeKind.CUSTOM, my_fn, {}, None)
        assert result == {"output": "result"}

    async def test_custom_callable_receives_input(self):
        received = {}

        async def capture_fn(inp):
            received.update(inp)
            return "captured"

        await run(AgentRuntimeKind.CUSTOM, capture_fn, {"key": "val"}, None)
        assert received == {"key": "val"}

    async def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unsupported"):
            await run("bad_kind", MagicMock(), {}, None)


class TestRunStream:
    async def test_compiled_graph_streams_events(self):
        instance = MagicMock()

        async def fake_events(*args, **kwargs):
            yield {"event": "on_chain_start", "data": {}}
            yield {"event": "on_chain_end", "data": {"output": "ok"}}

        instance.astream_events = fake_events

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.COMPILED_GRAPH, instance, {}, None):
            chunks.append(chunk)

        assert chunks[-1] == "data: [DONE]\n\n"
        event_chunks = chunks[:-1]
        assert len(event_chunks) == 2
        # Verify SSE format
        for chunk in event_chunks:
            assert chunk.startswith("data: ")
            assert chunk.endswith("\n\n")
            parsed = json.loads(chunk[len("data: ") :].strip())
            assert "event" in parsed

    async def test_compiled_graph_streams_done(self):
        instance = MagicMock()

        async def fake_events(*args, **kwargs):
            yield {"event": "on_chain_start"}
            yield {"event": "on_chain_end", "data": {"output": "ok"}}

        instance.astream_events = fake_events

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.COMPILED_GRAPH, instance, {}, None):
            chunks.append(chunk)

        assert chunks[-1] == "data: [DONE]\n\n"
        assert any("on_chain_start" in c for c in chunks)

    async def test_compiled_graph_with_session(self):
        instance = MagicMock()
        received_kwargs: dict = {}

        async def fake_events(*args, **kwargs):
            received_kwargs.update(kwargs)
            yield {"event": "on_chain_end"}

        instance.astream_events = fake_events

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.COMPILED_GRAPH, instance, {}, "sess-42"):
            chunks.append(chunk)

        assert received_kwargs.get("config") == {"configurable": {"thread_id": "sess-42"}}

    async def test_custom_astream_fallback(self):
        instance = MagicMock(spec=[])  # no attributes by default

        async def fake_astream(inp):
            yield "chunk1"
            yield "chunk2"

        instance.astream = fake_astream

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.CUSTOM, instance, {}, None):
            chunks.append(chunk)

        assert "data: [DONE]\n\n" in chunks
        # Should have 2 data chunks + DONE
        data_chunks = [c for c in chunks if c != "data: [DONE]\n\n"]
        assert len(data_chunks) == 2

    async def test_custom_ainvoke_fallback(self):
        """CUSTOM with ainvoke but no astream/astream_events falls back to ainvoke."""
        instance = MagicMock(spec=[])

        async def fake_ainvoke(inp):
            return "final_result"

        instance.ainvoke = fake_ainvoke

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.CUSTOM, instance, {}, None):
            chunks.append(chunk)

        assert "data: [DONE]\n\n" in chunks
        data_chunks = [c for c in chunks if c != "data: [DONE]\n\n"]
        assert len(data_chunks) == 1
        payload = json.loads(data_chunks[0][len("data: ") :].strip())
        assert payload == {"output": "final_result"}

    async def test_error_emits_error_event(self):
        instance = MagicMock()

        async def bad_events(*args, **kwargs):
            raise RuntimeError("boom")
            yield  # make it a generator

        instance.astream_events = bad_events

        chunks = []
        async for chunk in run_stream(AgentRuntimeKind.COMPILED_GRAPH, instance, {}, None):
            chunks.append(chunk)

        assert any("error" in c and "boom" in c for c in chunks)

    async def test_unknown_kind_emits_error_not_done(self):
        """Unknown kind emits an error SSE line and returns (no DONE)."""
        instance = MagicMock()
        chunks = []
        async for chunk in run_stream("bad_kind", instance, {}, None):
            chunks.append(chunk)

        assert len(chunks) >= 1
        assert any("unsupported" in c or "error" in c for c in chunks)
        # DONE should NOT appear when we early-return on unknown kind
        assert "data: [DONE]\n\n" not in chunks
