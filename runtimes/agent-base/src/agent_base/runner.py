"""Adapters that know how to call each supported agent framework."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from runtime_common.opik_tracing import is_opik_enabled
from runtime_common.schemas import AgentRuntimeKind


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)

try:
    from opik.integrations.langchain import OpikTracer as _LangChainOpikTracer

    _LANGCHAIN_OPIK = True
except ImportError:
    _LangChainOpikTracer = None  # type: ignore[assignment,misc]
    _LANGCHAIN_OPIK = False

try:
    from opik.integrations.adk import OpikTracer as _AdkOpikTracer
    from opik.integrations.adk import track_adk_agent_recursive as _track_adk

    _ADK_OPIK = True
except ImportError:
    _AdkOpikTracer = None  # type: ignore[assignment,misc]
    _track_adk = None  # type: ignore[assignment]
    _ADK_OPIK = False


def _make_langgraph_config(session_id: str | None, agent_name: str | None) -> dict | None:
    config: dict = {}
    if session_id:
        config["configurable"] = {"thread_id": session_id}
    if _LANGCHAIN_OPIK and _LangChainOpikTracer is not None and agent_name and is_opik_enabled():
        tracer = _LangChainOpikTracer(
            project_name=agent_name,
            thread_id=session_id,
            opik_context_read_only_mode=True,
        )
        config["callbacks"] = [tracer]
    return config or None


def _wrap_adk_with_opik(instance: Any, agent_name: str | None) -> Any:
    """Attach ADK-native OpikTracer to the agent (and sub-agents recursively).

    track_adk_agent_recursive mutates the agent in-place (sets before_*_callback).
    Guard with _opik_wrapped so cached factory instances are only wired once —
    the same OpikTracer works across invokes because it resolves the parent trace
    via contextvars at call time, not at construction time.
    """
    if not (_ADK_OPIK and _AdkOpikTracer is not None and agent_name and is_opik_enabled()):
        return instance
    if getattr(instance, "_opik_wrapped", False):
        return instance
    tracer = _AdkOpikTracer(name=f"agent:{agent_name}", project_name=agent_name)
    _track_adk(instance, tracer)  # type: ignore[arg-type]
    instance._opik_wrapped = True
    return instance


async def run(  # noqa: A002
    kind: str,
    instance: Any,
    input: dict,
    session_id: str | None,
    agent_name: str | None = None,
) -> dict:
    match kind:
        case AgentRuntimeKind.COMPILED_GRAPH:
            config = _make_langgraph_config(session_id, agent_name)
            result = await instance.ainvoke(input, config=config)
            return {"output": result}

        case AgentRuntimeKind.ADK:
            return await _run_adk(instance, input, session_id, agent_name)

        case AgentRuntimeKind.CUSTOM:
            if hasattr(instance, "ainvoke"):
                result = await instance.ainvoke(input)
            else:
                result = await instance(input)
            return {"output": result}

        case _:
            raise ValueError(f"unsupported agent runtime kind: {kind!r}")


async def run_stream(  # noqa: A002
    kind: str,
    instance: Any,
    input: dict,
    session_id: str | None,  # noqa: A002
    agent_name: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for streaming agent responses."""
    try:
        match kind:
            case AgentRuntimeKind.COMPILED_GRAPH:
                config = _make_langgraph_config(session_id, agent_name)
                streaming_emitted = False
                final_output: Any = None
                async for event in instance.astream_events(input, config=config, version="v2"):
                    yield f"data: {json.dumps(event, default=_json_default)}\n\n"
                    if event.get("event") == "on_chat_model_stream":
                        streaming_emitted = True
                    elif event.get("event") == "on_chain_end" and not event.get("parent_ids"):
                        final_output = event.get("data", {}).get("output")
                # Non-LLM graphs produce no on_chat_model_stream events. Emit the
                # root on_chain_end output so the BFF can surface it as text.
                if not streaming_emitted and final_output is not None:
                    yield f"data: {json.dumps({'output': final_output}, default=_json_default)}\n\n"

            case AgentRuntimeKind.ADK:
                async for line in _stream_adk(instance, input, session_id, agent_name):
                    yield line

            case AgentRuntimeKind.CUSTOM:
                if hasattr(instance, "astream_events"):
                    async for event in instance.astream_events(input):
                        yield f"data: {json.dumps(event, default=_json_default)}\n\n"
                elif hasattr(instance, "astream"):
                    async for chunk in instance.astream(input):
                        yield f"data: {json.dumps({'chunk': chunk}, default=_json_default)}\n\n"
                elif hasattr(instance, "ainvoke"):
                    result = await instance.ainvoke(input)
                    yield f"data: {json.dumps({'output': result}, default=_json_default)}\n\n"
                else:
                    result = await instance(input)
                    yield f"data: {json.dumps({'output': result}, default=_json_default)}\n\n"

            case _:
                yield f"data: {json.dumps({'error': f'unsupported agent runtime kind: {kind!r}'})}\n\n"  # noqa: E501
                return

    except Exception as exc:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        return

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# ADK helpers
# ---------------------------------------------------------------------------


def _adk_content(input: dict) -> object:  # noqa: A002
    """Convert invoke input dict to a google.genai Content object."""
    from google.genai import types as genai_types

    text = input.get("text") or input.get("message") or json.dumps(input)
    return genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=text)])


def _adk_runner(instance: Any) -> Any:
    """Wrap an ADK BaseAgent instance in a Runner with InMemorySessionService."""
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    return Runner(agent=instance, app_name="agent-base", session_service=InMemorySessionService())


async def _ensure_adk_session(runner: Any, uid: str, sid: str) -> None:
    """Create the (app_name, user_id, session_id) tuple if missing.

    Newer ADK Runner.run_async raises SessionNotFoundError if the session was
    not pre-created — older versions auto-created on first use. Calling
    create_session is safe even if it already exists for InMemorySessionService.
    """
    create = getattr(runner.session_service, "create_session", None)
    if create is None:
        return
    try:
        result = create(app_name=runner.app_name, user_id=uid, session_id=sid)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        # Session likely already exists — run_async will surface a real failure.
        pass


async def _run_adk(
    instance: Any,
    input: dict,  # noqa: A002
    session_id: str | None,
    agent_name: str | None = None,
) -> dict:
    """Run an ADK agent and return the final response text."""
    instance = _wrap_adk_with_opik(instance, agent_name)
    runner = _adk_runner(instance)
    content = _adk_content(input)
    uid = str(session_id or "anon")
    sid = str(session_id or "default")
    await _ensure_adk_session(runner, uid, sid)

    final_text = ""
    async for event in runner.run_async(user_id=uid, session_id=sid, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = " ".join(
                p.text for p in event.content.parts if hasattr(p, "text") and p.text
            )

    return {"output": final_text}


async def _stream_adk(
    instance: Any,
    input: dict,
    session_id: str | None,  # noqa: A002
    agent_name: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE lines for each ADK event."""
    instance = _wrap_adk_with_opik(instance, agent_name)
    runner = _adk_runner(instance)
    content = _adk_content(input)
    uid = str(session_id or "anon")
    sid = str(session_id or "default")
    await _ensure_adk_session(runner, uid, sid)

    async for event in runner.run_async(user_id=uid, session_id=sid, new_message=content):
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        else:
            payload = {"event": str(event)}
        yield f"data: {json.dumps(payload)}\n\n"
