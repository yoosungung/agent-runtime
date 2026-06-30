"""Agent delegate bridge for Hermes — mirror MCP invoke-internal."""

from __future__ import annotations

import json
import uuid

from hermes_base.context import get_current_delegate_depth, get_current_token
from hermes_base.http_client import get_agent_http_client


async def invoke_agent_delegate(
    gateway_url: str,
    agent: str,
    task: str,
    *,
    token: str | None = None,
    depth: int | None = None,
    timeout_sec: float = 60.0,
) -> object:
    """POST {gateway}/v1/agents/invoke-internal with JWT forward."""
    headers = {
        "X-Runtime-Caller": "agent-pool",
        "X-Runtime-Delegate-Depth": str(
            depth if depth is not None else get_current_delegate_depth() + 1
        ),
    }
    bearer = token if token is not None else get_current_token()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
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


def build_runtime_agent_env(
    gateway_url: str,
    delegate_agents: list[str],
) -> None:
    """Expose delegate agent list to hermes-agent via env."""
    import os

    os.environ["RUNTIME_AGENT_GATEWAY_URL"] = gateway_url
    os.environ["RUNTIME_DELEGATE_AGENTS_JSON"] = json.dumps(
        delegate_agents,
        ensure_ascii=False,
    )
