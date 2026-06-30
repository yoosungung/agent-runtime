"""MCP gateway tool wrappers for general-tier agents."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from agent_base.context import get_current_token
from agent_base.http_client import get_mcp_http_client
from agent_base.knowledge_context import get_current_bindings
from runtime_common.knowledge import (
    KnowledgeScopeError,
    ensure_bindings_for_server,
    invoke_scoped_retrieval,
)


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
    mcp_requires_knowledge: set[str] | None = None,
) -> list[StructuredTool]:
    """Build LangChain tools from cached MCP tool manifest."""
    gateway = gateway_url or os.environ["MCP_GATEWAY_URL"]
    requires_knowledge = mcp_requires_knowledge or set()
    tools: list[StructuredTool] = []

    for entry in mcp_tools:
        server = entry["server"]
        name = entry["name"]
        description = entry.get("description") or f"MCP tool {name} on {server}"
        schema = _make_tool_schema(name)
        server_requires = server in requires_knowledge

        async def _invoke(
            arguments: dict[str, Any] | None = None,
            *,
            _server: str = server,
            _name: str = name,
            _requires: bool = server_requires,
        ) -> str:
            args = arguments or {}
            bindings = get_current_bindings()
            try:
                ensure_bindings_for_server(
                    _server,
                    requires_knowledge=_requires,
                    bindings=bindings,
                )
            except KnowledgeScopeError as exc:
                return _stringify({"error": str(exc)})

            async def call_mcp(tool: str, scoped_args: dict[str, Any]) -> object:
                return await _call_mcp(
                    gateway,
                    _server,
                    tool,
                    scoped_args,
                    get_current_token(),
                )

            if bindings:
                result = await invoke_scoped_retrieval(
                    _name,
                    args,
                    bindings=bindings,
                    call_mcp=call_mcp,
                )
            else:
                result = await call_mcp(_name, args)
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
