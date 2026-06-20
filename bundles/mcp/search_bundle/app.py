"""MCP SDK search-server bundle — Naver web search + URL fetch.

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:mcp_sdk"
    name         = "search-server"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server

from runtime_common.providers.mcp_sdk import get_mask_error_details

_bundle_dir = Path(__file__).resolve().parent
if str(_bundle_dir) not in sys.path:
    sys.path.insert(0, str(_bundle_dir))

from models import SearchSettings  # noqa: E402
from providers import get_naver_provider, get_url_fetcher  # noqa: E402


def build_server(cfg: dict, secrets) -> Any:
    search_settings = SearchSettings.from_cfg(cfg)
    naver = get_naver_provider(cfg, secrets)
    fetcher = get_url_fetcher(cfg)
    max_display = naver.max_display

    server = Server("search-server")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="naver_search",
                description="Search the Korean web via Naver and return the top results.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "display": {
                            "type": "integer",
                            "description": f"Number of results (1-{max_display}, default 5).",
                            "minimum": 1,
                            "maximum": max_display,
                            "default": 5,
                        },
                        "start": {
                            "type": "integer",
                            "description": "Search start position (1-1000, default 1).",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 1,
                        },
                        "category": {
                            "type": "string",
                            "enum": ["web", "blog", "news"],
                            "default": search_settings.default_category,
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["sim", "date"],
                            "default": "sim",
                            "description": "Sort order for blog/news results.",
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="fetch_url",
                description="Fetch a URL via HTTP GET and return the body (truncated).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Absolute http(s):// URL"},
                        "timeout_seconds": {"type": "number", "default": 10.0},
                        "extract_text": {
                            "type": "boolean",
                            "default": False,
                            "description": "Strip HTML to plain text when Content-Type is text/html.",
                        },
                    },
                    "required": ["url"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name == "naver_search":
            result = await naver.search(
                query=arguments["query"],
                display=int(arguments.get("display", 5)),
                start=int(arguments.get("start", 1)),
                category=str(arguments.get("category", search_settings.default_category)),  # type: ignore[arg-type]
                sort=str(arguments.get("sort", "sim")),  # type: ignore[arg-type]
            )
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(result.to_dict(), ensure_ascii=False),
                )
            ]
        if name == "fetch_url":
            text = await fetcher.fetch(
                url=arguments["url"],
                timeout_seconds=float(arguments.get("timeout_seconds", 10.0)),
                extract_text=bool(arguments.get("extract_text", False)),
            )
            return [types.TextContent(type="text", text=text)]
        raise ValueError(f"unknown tool: {name!r}")

    return _Adapter(server, _list_tools, _call_tool, get_mask_error_details(cfg))


class _Adapter:
    """Bridges ``mcp.Server`` decorator-registered handlers to mcp-base's dispatch shape."""

    def __init__(self, server, list_tools_fn, call_tool_fn, mask_errors: bool) -> None:
        self._server = server
        self._list_tools_fn = list_tools_fn
        self._call_tool_fn = call_tool_fn
        self._mask_errors = mask_errors

    async def list_tools(self) -> list[dict]:
        tools = await self._list_tools_fn()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema,
            }
            for t in tools
        ]

    async def dispatch(self, tool: str, arguments: dict) -> Any:
        try:
            blocks = await self._call_tool_fn(tool, arguments)
        except Exception as exc:
            if self._mask_errors:
                raise RuntimeError("tool call failed") from None
            raise exc
        if len(blocks) == 1 and isinstance(blocks[0], types.TextContent):
            text = blocks[0].text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return [b.model_dump() if hasattr(b, "model_dump") else str(b) for b in blocks]
