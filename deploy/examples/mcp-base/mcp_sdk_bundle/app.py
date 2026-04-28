"""MCP SDK search-server bundle — Naver web search + URL fetch.

Two tools registered via the official ``mcp.server.lowlevel.Server``:
  * ``naver_search(query, display)`` — calls Naver web search REST API
  * ``fetch_url(url, timeout_seconds)`` — HTTP GET, body truncated to 8 KB

The SDK Server is wrapped with a thin ``_Adapter`` so the mcp-base runner can
call ``dispatch()`` / ``list_tools()`` directly (the SDK is otherwise
stdio/HTTP-only).

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:mcp_sdk"

Bundle deps (in this bundle's ``pyproject.toml``): ``mcp>=1.27``, ``httpx>=0.27``.

API keys — passed via ``source_meta.config`` (per the project convention for
tool-specific credentials), NOT via secrets_ref:

    {
      "mcp": {"mask_error_details": false},
      "naver": {
        "client_id":     "<naver app client id>",
        "client_secret": "<naver app client secret>"
      }
    }

Without the ``naver`` block ``naver_search`` returns a clear error;
``fetch_url`` works regardless.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from mcp import types
from mcp.server.lowlevel import Server

from runtime_common.providers.mcp_sdk import get_mask_error_details

_NAVER_WEB_ENDPOINT = "https://openapi.naver.com/v1/search/webkr.json"


def build_server(cfg: dict, secrets) -> Any:  # noqa: ARG001 — secrets unused for this bundle
    server = Server("search-server")
    naver_cfg = cfg.get("naver") or {}
    naver_client_id = naver_cfg.get("client_id")
    naver_client_secret = naver_cfg.get("client_secret")

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
                            "description": "Number of results (1-10, default 5).",
                            "minimum": 1,
                            "maximum": 10,
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="fetch_url",
                description="Fetch a URL via HTTP GET and return the body (truncated to 8 KB).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Absolute http(s):// URL"},
                        "timeout_seconds": {"type": "number", "default": 10.0},
                    },
                    "required": ["url"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name == "naver_search":
            data = await _naver_search(
                query=arguments["query"],
                display=int(arguments.get("display", 5)),
                client_id=naver_client_id,
                client_secret=naver_client_secret,
            )
            return [types.TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]
        if name == "fetch_url":
            text = await _fetch_url(
                url=arguments["url"],
                timeout_seconds=float(arguments.get("timeout_seconds", 10.0)),
            )
            return [types.TextContent(type="text", text=text)]
        raise ValueError(f"unknown tool: {name!r}")

    return _Adapter(server, _list_tools, _call_tool, get_mask_error_details(cfg))


async def _naver_search(
    *, query: str, display: int, client_id: str | None, client_secret: str | None
) -> dict:
    if not (client_id and client_secret):
        raise RuntimeError(
            "naver credentials missing: set source_meta.config.naver.{client_id,client_secret}"
        )
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": query, "display": display}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_NAVER_WEB_ENDPOINT, headers=headers, params=params)
        resp.raise_for_status()
        body = resp.json()
    return {
        "query": query,
        "total": body.get("total", 0),
        "items": [
            {"title": _strip_tags(item.get("title", "")), "link": item.get("link", "")}
            for item in body.get("items", [])
        ],
    }


async def _fetch_url(*, url: str, timeout_seconds: float) -> str:  # noqa: ASYNC109
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text[:8192]


def _strip_tags(text: str) -> str:
    """Naver wraps query matches in <b>...</b> — strip for readability."""
    return text.replace("<b>", "").replace("</b>", "")


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
