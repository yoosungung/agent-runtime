"""Adapters that dispatch a tool call to the right MCP framework.

A deployed MCP bundle's entrypoint is a zero-arg factory that returns the
framework-native server object (a FastMCP instance, an mcp.Server, or a
custom duck-typed server implementing .call(tool, arguments) / .list_tools()).
"""

from __future__ import annotations

from typing import Any

from runtime_common.schemas import McpRuntimeKind


async def run(kind: str, instance: Any, tool: str, arguments: dict) -> dict:
    match kind:
        case McpRuntimeKind.FASTMCP:
            tool_result = await instance.call_tool(tool, arguments)
            # FastMCP 3.x returns ToolResult; serialize via model_dump or fallback
            if hasattr(tool_result, "structured_content") and tool_result.structured_content:
                result = tool_result.structured_content
            elif hasattr(tool_result, "content"):
                result = [
                    c.model_dump() if hasattr(c, "model_dump") else str(c)
                    for c in tool_result.content
                ]
            elif hasattr(tool_result, "model_dump"):
                result = tool_result.model_dump()
            else:
                result = str(tool_result)
            return {"result": result}

        case McpRuntimeKind.MCP_SDK:
            # mcp.Server exposes a request handler map; the bundle is expected
            # to also export an async callable dispatch(tool, arguments).
            if hasattr(instance, "dispatch"):
                result = await instance.dispatch(tool, arguments)
            else:
                handler = instance.request_handlers.get(tool)
                if handler is None:
                    raise ValueError(f"tool not registered: {tool!r}")
                result = await handler(arguments)
            return {"result": result}

        case McpRuntimeKind.CUSTOM:
            result = await instance.call(tool, arguments)
            return {"result": result}

        case _:
            raise ValueError(f"unsupported mcp runtime kind: {kind!r}")


async def list_tools(kind: str, instance: Any) -> list[dict]:
    """Return a list of tool descriptors for the given MCP server instance."""
    match kind:
        case McpRuntimeKind.FASTMCP:
            # FastMCP 3.x: list_tools() returns FunctionTool objects
            tools = await instance.list_tools()
            result = []
            for t in tools:
                # to_mcp_tool() gives the canonical MCP Tool with inputSchema
                if hasattr(t, "to_mcp_tool"):
                    mcp_t = t.to_mcp_tool()
                    result.append(
                        {
                            "name": mcp_t.name,
                            "description": mcp_t.description or "",
                            "inputSchema": mcp_t.inputSchema
                            if isinstance(mcp_t.inputSchema, dict)
                            else mcp_t.inputSchema.model_dump(),
                        }
                    )
                else:
                    result.append(
                        {
                            "name": t.name,
                            "description": getattr(t, "description", ""),
                            "inputSchema": getattr(t, "parameters", {}),
                        }
                    )
            return result

        case McpRuntimeKind.MCP_SDK:
            if hasattr(instance, "list_tools"):
                raw = await instance.list_tools()
                if isinstance(raw, list):
                    return raw
                # mcp SDK may return a ListToolsResult with .tools attribute
                if hasattr(raw, "tools"):
                    return [
                        {
                            "name": t.name,
                            "description": getattr(t, "description", ""),
                            "inputSchema": getattr(t, "inputSchema", {}),
                        }
                        for t in raw.tools
                    ]
            # Fallback: enumerate registered handler keys
            handlers = getattr(instance, "request_handlers", {})
            return [{"name": name} for name in handlers]

        case McpRuntimeKind.CUSTOM:
            if hasattr(instance, "list_tools"):
                raw = await instance.list_tools()
                if isinstance(raw, list):
                    return raw
            return []

        case _:
            raise ValueError(f"unsupported mcp runtime kind: {kind!r}")
