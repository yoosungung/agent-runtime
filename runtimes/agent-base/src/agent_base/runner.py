"""Adapters that know how to call each supported agent framework."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from runtime_common.opik_tracing import is_opik_enabled
from runtime_common.providers.pg_infra import get_adk_session_service
from runtime_common.schemas import AgentRuntimeKind
from runtime_common.secrets import SecretResolver


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


def _extract_langgraph_stream_text(event: dict) -> str | None:
    """Surface user-facing token deltas from LangGraph astream_events v2."""
    if event.get("event") != "on_chat_model_stream":
        return None
    chunk = event.get("data", {}).get("chunk")
    if not isinstance(chunk, dict):
        return None
    content = chunk.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        joined = "".join(parts)
        return joined or None
    return None


def _compiled_graph_input(input: dict) -> dict:  # noqa: A002
    """Normalize platform invoke payload to LangGraph AgentState input."""
    if input.get("messages"):
        return input
    text = input.get("message")
    if text is None:
        text = input.get("text")
    if text is None:
        return input
    payload = {k: v for k, v in input.items() if k not in ("message", "text")}
    return {**payload, "messages": [{"role": "user", "content": text}]}


def _adk_user_session_ids(
    session_id: str | None,
    principal_user_id: int | str | None,
) -> tuple[str, str]:
    uid = str(principal_user_id or session_id or "anon")
    sid = str(session_id or "default")
    return uid, sid


async def _call_with_session(
    method: Callable[..., Any],
    input: dict,  # noqa: A002
    session_id: str | None,
) -> Any:
    """Invoke a custom agent method, passing session_id/config when supported."""
    config = _make_langgraph_config(session_id, None)
    kwargs: dict[str, Any] = {}
    if session_id is not None:
        kwargs["session_id"] = session_id
    if config is not None:
        kwargs["config"] = config

    if kwargs:
        try:
            result = method(input, **kwargs)
        except TypeError:
            result = method(input)
    else:
        result = method(input)
    if inspect.isawaitable(result):
        return await result
    return result


async def _run_custom(
    instance: Any,
    input: dict,  # noqa: A002
    session_id: str | None,
) -> dict:
    if hasattr(instance, "ainvoke"):
        result = await _call_with_session(instance.ainvoke, input, session_id)
    else:
        result = await _call_with_session(instance, input, session_id)
    return {"output": result}


async def _stream_custom(
    instance: Any,
    input: dict,
    session_id: str | None,
) -> AsyncIterator[str]:
    if hasattr(instance, "astream_events"):
        config = _make_langgraph_config(session_id, None)
        kwargs: dict[str, Any] = {}
        try:
            sig = inspect.signature(instance.astream_events)
            if session_id is not None and "session_id" in sig.parameters:
                kwargs["session_id"] = session_id
            if config is not None and "config" in sig.parameters:
                kwargs["config"] = config
        except (ValueError, TypeError):
            pass

        if kwargs:
            events = instance.astream_events(input, **kwargs)
        else:
            events = instance.astream_events(input)
        async for event in events:
            yield f"data: {json.dumps(event, default=_json_default)}\n\n"
    elif hasattr(instance, "astream"):
        stream = instance.astream(input)
        async for chunk in stream:
            yield f"data: {json.dumps({'chunk': chunk}, default=_json_default)}\n\n"
    elif hasattr(instance, "ainvoke"):
        result = await _call_with_session(instance.ainvoke, input, session_id)
        yield f"data: {json.dumps({'output': result}, default=_json_default)}\n\n"
    else:
        result = await _call_with_session(instance, input, session_id)
        yield f"data: {json.dumps({'output': result}, default=_json_default)}\n\n"


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
    *,
    cfg: dict | None = None,
    secrets: SecretResolver | None = None,
    principal_user_id: int | str | None = None,
    adk_session_cache: dict[str, Any] | None = None,
) -> dict:
    match kind:
        case AgentRuntimeKind.COMPILED_GRAPH:
            config = _make_langgraph_config(session_id, agent_name)
            graph_input = _compiled_graph_input(input)
            result = await instance.ainvoke(graph_input, config=config)
            return {"output": result}

        case AgentRuntimeKind.ADK:
            return await _run_adk(
                instance,
                input,
                session_id,
                agent_name,
                cfg=cfg or {},
                secrets=secrets,
                principal_user_id=principal_user_id,
                adk_session_cache=adk_session_cache,
            )

        case AgentRuntimeKind.CUSTOM:
            return await _run_custom(instance, input, session_id)

        case _:
            raise ValueError(f"unsupported agent runtime kind: {kind!r}")


async def run_stream(  # noqa: A002
    kind: str,
    instance: Any,
    input: dict,
    session_id: str | None,  # noqa: A002
    agent_name: str | None = None,
    *,
    cfg: dict | None = None,
    secrets: SecretResolver | None = None,
    principal_user_id: int | str | None = None,
    adk_session_cache: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for streaming agent responses."""
    try:
        match kind:
            case AgentRuntimeKind.COMPILED_GRAPH:
                config = _make_langgraph_config(session_id, agent_name)
                graph_input = _compiled_graph_input(input)
                streaming_emitted = False
                final_output: Any = None
                async for event in instance.astream_events(graph_input, config=config, version="v2"):
                    text = _extract_langgraph_stream_text(event)
                    if text:
                        yield f"data: {json.dumps({'text': text})}\n\n"
                        streaming_emitted = True
                    elif event.get("event") == "on_chain_end" and not event.get("parent_ids"):
                        final_output = event.get("data", {}).get("output")
                # Non-LLM graphs produce no on_chat_model_stream events. Emit the
                # root on_chain_end output so the BFF can surface it as text.
                if not streaming_emitted and final_output is not None:
                    yield f"data: {json.dumps({'output': final_output}, default=_json_default)}\n\n"

            case AgentRuntimeKind.ADK:
                async for line in _stream_adk(
                    instance,
                    input,
                    session_id,
                    agent_name,
                    cfg=cfg or {},
                    secrets=secrets,
                    principal_user_id=principal_user_id,
                    adk_session_cache=adk_session_cache,
                ):
                    yield line

            case AgentRuntimeKind.CUSTOM:
                async for line in _stream_custom(instance, input, session_id):
                    yield line

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


def _adk_runner(instance: Any, session_service: Any) -> Any:
    """Wrap an ADK BaseAgent instance in a Runner with the given session service."""
    from google.adk.runners import Runner

    return Runner(agent=instance, app_name="agent-base", session_service=session_service)


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


def _resolve_adk_session_service(
    cfg: dict,
    secrets: SecretResolver | None,
    adk_session_cache: dict[str, Any] | None,
) -> Any:
    if secrets is None:
        from google.adk.sessions import InMemorySessionService

        return InMemorySessionService()
    cache = adk_session_cache if adk_session_cache is not None else {}
    return get_adk_session_service(cfg, secrets, cache)


async def _run_adk(
    instance: Any,
    input: dict,  # noqa: A002
    session_id: str | None,
    agent_name: str | None = None,
    *,
    cfg: dict,
    secrets: SecretResolver | None = None,
    principal_user_id: int | str | None = None,
    adk_session_cache: dict[str, Any] | None = None,
) -> dict:
    """Run an ADK agent and return the final response text."""
    instance = _wrap_adk_with_opik(instance, agent_name)
    session_service = _resolve_adk_session_service(cfg, secrets, adk_session_cache)
    runner = _adk_runner(instance, session_service)
    content = _adk_content(input)
    uid, sid = _adk_user_session_ids(session_id, principal_user_id)
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
    *,
    cfg: dict,
    secrets: SecretResolver | None = None,
    principal_user_id: int | str | None = None,
    adk_session_cache: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Yield SSE lines for each ADK event."""
    instance = _wrap_adk_with_opik(instance, agent_name)
    session_service = _resolve_adk_session_service(cfg, secrets, adk_session_cache)
    runner = _adk_runner(instance, session_service)
    content = _adk_content(input)
    uid, sid = _adk_user_session_ids(session_id, principal_user_id)
    await _ensure_adk_session(runner, uid, sid)

    async for event in runner.run_async(user_id=uid, session_id=sid, new_message=content):
        if hasattr(event, "model_dump"):
            payload = event.model_dump(mode="json")
        else:
            payload = {"event": str(event)}
        yield f"data: {json.dumps(payload)}\n\n"
