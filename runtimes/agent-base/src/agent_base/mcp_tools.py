"""MCP gateway tool wrappers for general-tier agents."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from agent_base.context import get_current_token


async def _call_mcp(
    gateway_url: str,
    server: str,
    tool: str,
    arguments: dict[str, Any],
    token: str | None,
) -> object:
    headers = {"X-Runtime-Caller": "agent-pool"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"server": server, "tool": tool, "arguments": arguments}
    async with httpx.AsyncClient(timeout=30.0) as client:
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


def _stringify(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict | list):
        return json.dumps(obj, ensure_ascii=False)
    return str(obj)


def _make_tool_schema(tool_name: str) -> type[BaseModel]:
    """Minimal open schema — MCP servers validate arguments server-side."""
    return create_model(
        f"Mcp_{tool_name}_args",
        __base__=BaseModel,
        arguments=(dict[str, Any], Field(default_factory=dict, description="Tool arguments")),
    )


def build_mcp_tools(
    mcp_tools: list[dict[str, str]],
    *,
    gateway_url: str | None = None,
) -> list[StructuredTool]:
    """Build LangChain tools from cached MCP tool manifest."""
    gateway = gateway_url or os.environ["MCP_GATEWAY_URL"]
    tools: list[StructuredTool] = []

    for entry in mcp_tools:
        server = entry["server"]
        name = entry["name"]
        description = entry.get("description") or f"MCP tool {name} on {server}"
        schema = _make_tool_schema(name)

        async def _invoke(
            arguments: dict[str, Any] | None = None,
            *,
            _server: str = server,
            _name: str = name,
        ) -> str:
            args = arguments or {}
            result = await _call_mcp(
                gateway, _server, _name, args, get_current_token()
            )
            return _stringify(result)

        tools.append(
            StructuredTool(
                name=name,
                description=description,
                coroutine=_invoke,
                args_schema=schema,
            )
        )

    return tools
