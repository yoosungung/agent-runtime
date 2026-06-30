"""Agent delegate tool wrappers — mirror MCP internal invoke."""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from agent_base.context import get_current_token, get_delegate_depth
from agent_base.http_client import get_agent_http_client

DEFAULT_MAX_DELEGATE_DEPTH = 3
DEFAULT_DELEGATE_TIMEOUT_SEC = 60.0


async def _call_agent_delegate(
    gateway_url: str,
    agent: str,
    task: str,
    token: str | None,
    *,
    depth: int,
    timeout_sec: float,
) -> object:
    headers = {
        "X-Runtime-Caller": "agent-pool",
        "X-Runtime-Delegate-Depth": str(depth),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "agent": agent,
        "input": {"message": task},
        "session_id": str(uuid.uuid4()),
    }
    client = get_agent_http_client()
    resp = await client.post(
        f"{gateway_url.rstrip('/')}/v1/agents/invoke-internal",
        json=payload,
        headers=headers,
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _stringify(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict | list):
        return json.dumps(obj, ensure_ascii=False)
    return str(obj)


def _extract_output(result: object) -> str:
    if isinstance(result, dict) and "output" in result:
        return _stringify(result["output"])
    return _stringify(result)


def _make_delegate_schema(agent_name: str) -> type[BaseModel]:
    safe = agent_name.replace("-", "_").replace(".", "_")
    return create_model(
        f"Delegate_{safe}_args",
        __base__=BaseModel,
        task=(str, Field(..., description="Task description for the delegate agent")),
    )


def build_agent_delegate_tools(
    delegate_agents: list[str],
    *,
    gateway_url: str,
    allow_delegation: bool = True,
    max_depth: int = DEFAULT_MAX_DELEGATE_DEPTH,
    delegate_timeout_sec: float = DEFAULT_DELEGATE_TIMEOUT_SEC,
) -> list[StructuredTool]:
    """Build LangChain tools that invoke other agents via invoke-internal."""
    if not allow_delegation or not delegate_agents:
        return []
    if get_delegate_depth() >= max_depth:
        return []

    tools: list[StructuredTool] = []
    next_depth = get_delegate_depth() + 1

    for agent_name in delegate_agents:
        schema = _make_delegate_schema(agent_name)
        description = (
            f"Delegate a focused task to agent '{agent_name}'. "
            "Provide a complete, self-contained task description."
        )

        async def _invoke(
            task: str,
            *,
            _agent: str = agent_name,
            _depth: int = next_depth,
        ) -> str:
            result = await _call_agent_delegate(
                gateway_url,
                _agent,
                task,
                get_current_token(),
                depth=_depth,
                timeout_sec=delegate_timeout_sec,
            )
            return _extract_output(result)

        tools.append(
            StructuredTool(
                name=f"delegate_{agent_name.replace('-', '_')}",
                description=description,
                coroutine=_invoke,
                args_schema=schema,
            )
        )

    return tools
