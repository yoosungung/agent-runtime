"""MCP gateway bridge for Hermes runtime_mcp toolset."""

from __future__ import annotations

import json
import os
from typing import Any

from hermes_base.context import get_current_token
from hermes_base.http_client import get_mcp_http_client
from hermes_base.schemas import McpToolManifestEntry


async def invoke_mcp_tool(
    gateway_url: str,
    server: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    token: str | None = None,
) -> object:
    """POST {gateway}/v1/mcp/invoke-internal with JWT forward."""
    headers = {"X-Runtime-Caller": "agent-pool"}
    bearer = token if token is not None else get_current_token()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    payload = {"server": server, "tool": tool, "arguments": arguments or {}}
    client = get_mcp_http_client()
    resp = await client.post(
        f"{gateway_url.rstrip('/')}/v1/mcp/invoke-internal",
        json=payload,
        headers=headers,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return resp.text


def build_runtime_mcp_env(
    gateway_url: str,
    mcp_tools: list[McpToolManifestEntry],
) -> None:
    """Expose MCP manifest to hermes-agent runtime_mcp toolset via env."""
    os.environ["RUNTIME_MCP_GATEWAY_URL"] = gateway_url
    os.environ["RUNTIME_MCP_TOOLS_JSON"] = json.dumps(
        [t.model_dump() for t in mcp_tools],
        ensure_ascii=False,
    )
