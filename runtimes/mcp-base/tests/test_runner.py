"""Unit tests for mcp-base runner adapters."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_base.runner import list_tools, run
from runtime_common.schemas import McpRuntimeKind


def _make_tool_result(content_items: list | None = None, structured: dict | None = None):
    """Build a FastMCP 3.x ToolResult-like mock."""
    tr = MagicMock(spec=["structured_content", "content"])
    tr.structured_content = structured
    content = content_items or []
    # Each content item is a model with .model_dump()
    tr.content = [MagicMock(spec=["model_dump"], **{"model_dump.return_value": c}) for c in content]
    return tr


class TestRun:
    async def test_fastmcp_call_tool(self):
        # FastMCP 3.x returns ToolResult with .content list
        tool_result = _make_tool_result(content_items=[{"type": "text", "text": "value"}])
        instance = AsyncMock()
        instance.call_tool.return_value = tool_result
        result = await run(McpRuntimeKind.FASTMCP, instance, "my_tool", {"arg": 1})
        assert result == {"result": [{"type": "text", "text": "value"}]}
        instance.call_tool.assert_called_once_with("my_tool", {"arg": 1})

    async def test_fastmcp_structured_content(self):
        # FastMCP 3.x structured output takes priority
        tool_result = _make_tool_result(structured={"data": "value"})
        instance = AsyncMock()
        instance.call_tool.return_value = tool_result
        result = await run(McpRuntimeKind.FASTMCP, instance, "my_tool", {})
        assert result == {"result": {"data": "value"}}

    async def test_fastmcp_empty_content(self):
        tool_result = _make_tool_result(content_items=[])
        instance = AsyncMock()
        instance.call_tool.return_value = tool_result
        result = await run(McpRuntimeKind.FASTMCP, instance, "ping", {})
        assert result == {"result": []}
        instance.call_tool.assert_called_once_with("ping", {})

    async def test_mcp_sdk_with_dispatch(self):
        instance = AsyncMock()
        instance.dispatch.return_value = "sdk_result"
        result = await run(McpRuntimeKind.MCP_SDK, instance, "search", {"q": "hello"})
        assert result == {"result": "sdk_result"}
        instance.dispatch.assert_called_once_with("search", {"q": "hello"})

    async def test_mcp_sdk_without_dispatch_uses_handler(self):
        handler = AsyncMock(return_value="handler_result")
        instance = MagicMock(spec=[])
        instance.request_handlers = {"my_tool": handler}
        result = await run(McpRuntimeKind.MCP_SDK, instance, "my_tool", {"x": 1})
        assert result == {"result": "handler_result"}
        handler.assert_called_once_with({"x": 1})

    async def test_mcp_sdk_missing_handler_raises(self):
        instance = MagicMock(spec=[])
        instance.request_handlers = {}
        with pytest.raises(ValueError, match="tool not registered"):
            await run(McpRuntimeKind.MCP_SDK, instance, "unknown", {})

    async def test_custom_call(self):
        instance = AsyncMock()
        instance.call.return_value = "custom_result"
        result = await run(McpRuntimeKind.CUSTOM, instance, "search", {})
        assert result == {"result": "custom_result"}
        instance.call.assert_called_once_with("search", {})

    async def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unsupported"):
            await run("bad_kind", MagicMock(), "tool", {})


class TestListTools:
    async def test_fastmcp_list_tools_with_to_mcp_tool(self):
        """FastMCP 3.x: tool objects have to_mcp_tool() returning an MCP Tool."""
        mcp_tool = MagicMock()
        mcp_tool.name = "my_tool"
        mcp_tool.description = "A tool"
        mcp_tool.inputSchema = {"type": "object", "properties": {}}

        tool = MagicMock()
        tool.to_mcp_tool.return_value = mcp_tool

        instance = AsyncMock()
        instance.list_tools.return_value = [tool]

        result = await list_tools(McpRuntimeKind.FASTMCP, instance)
        assert len(result) == 1
        assert result[0]["name"] == "my_tool"
        assert result[0]["description"] == "A tool"
        assert result[0]["inputSchema"] == {"type": "object", "properties": {}}

    async def test_fastmcp_list_tools_fallback(self):
        """Tools without to_mcp_tool() fall back to .name/.description/.parameters."""
        tool = MagicMock(spec=["name", "description", "parameters"])
        tool.name = "bare_tool"
        tool.description = "desc"
        tool.parameters = {"type": "object"}

        instance = AsyncMock()
        instance.list_tools.return_value = [tool]

        result = await list_tools(McpRuntimeKind.FASTMCP, instance)
        assert result[0]["name"] == "bare_tool"
        assert result[0]["description"] == "desc"
        assert result[0]["inputSchema"] == {"type": "object"}

    async def test_fastmcp_list_tools_no_description(self):
        """Fallback path: tool without description attribute."""
        tool = MagicMock(spec=["name", "parameters"])
        tool.name = "bare_tool"
        tool.parameters = {}

        instance = AsyncMock()
        instance.list_tools.return_value = [tool]

        result = await list_tools(McpRuntimeKind.FASTMCP, instance)
        assert result[0]["name"] == "bare_tool"
        assert result[0]["description"] == ""

    async def test_fastmcp_empty_tools(self):
        instance = AsyncMock()
        instance.list_tools.return_value = []
        result = await list_tools(McpRuntimeKind.FASTMCP, instance)
        assert result == []

    async def test_mcp_sdk_list_tools_plain_list(self):
        """mcp.Server returns a plain list from list_tools."""
        raw = [{"name": "tool_a"}, {"name": "tool_b"}]
        instance = AsyncMock()
        instance.list_tools.return_value = raw
        result = await list_tools(McpRuntimeKind.MCP_SDK, instance)
        assert result == raw

    async def test_mcp_sdk_list_tools_result_object(self):
        """mcp.Server may return a ListToolsResult with .tools attribute."""
        inner_tool = MagicMock()
        inner_tool.name = "wrapped_tool"
        inner_tool.description = "desc"
        inner_tool.inputSchema = {"type": "object"}

        list_result = MagicMock()
        list_result.__iter__ = MagicMock(side_effect=TypeError)  # not a list
        list_result.tools = [inner_tool]

        instance = AsyncMock()
        instance.list_tools.return_value = list_result

        result = await list_tools(McpRuntimeKind.MCP_SDK, instance)
        assert len(result) == 1
        assert result[0]["name"] == "wrapped_tool"

    async def test_mcp_sdk_fallback_to_handler_keys(self):
        """When instance has no list_tools, fall back to request_handlers keys."""
        instance = MagicMock(spec=[])
        instance.request_handlers = {"tool_x": AsyncMock(), "tool_y": AsyncMock()}

        result = await list_tools(McpRuntimeKind.MCP_SDK, instance)
        names = {r["name"] for r in result}
        assert names == {"tool_x", "tool_y"}

    async def test_custom_list_tools_delegates(self):
        raw = [{"name": "search"}]
        instance = AsyncMock()
        instance.list_tools.return_value = raw
        result = await list_tools(McpRuntimeKind.CUSTOM, instance)
        assert result == raw

    async def test_custom_list_tools_no_method_returns_empty(self):
        instance = MagicMock(spec=[])  # no list_tools
        result = await list_tools(McpRuntimeKind.CUSTOM, instance)
        assert result == []

    async def test_unknown_kind_raises(self):
        instance = MagicMock()
        with pytest.raises(ValueError, match="unsupported"):
            await list_tools("bad_kind", instance)
