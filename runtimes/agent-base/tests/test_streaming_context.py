"""Streaming invoke must set JWT inside the generator context."""

from contextlib import aclosing

from agent_base.context import get_current_token, set_current_token


async def test_set_token_inside_generator_without_reset():
    """Fixed pattern: set JWT inside the streaming generator; no reset in finally."""
    seen: list[str | None] = []

    async def fixed_stream():
        set_current_token("stream-jwt")
        seen.append(get_current_token())
        yield "chunk"

    async with aclosing(fixed_stream()) as stream:
        async for _ in stream:
            pass

    assert seen == ["stream-jwt"]


async def test_invoke_streaming_pattern_exposes_jwt_to_run_stream():
    """Mirror /invoke streaming path used by agent-base app.py."""
    seen: list[str | None] = []
    bearer_token = "stream-jwt"

    async def fake_run_stream(*args, **kwargs):
        seen.append(get_current_token())
        yield "data: ok\n\n"

    async def stream_with_counter():
        set_current_token(bearer_token)
        async for chunk in fake_run_stream():
            yield chunk

    async with aclosing(stream_with_counter()) as stream:
        async for _ in stream:
            pass

    assert seen == ["stream-jwt"]
