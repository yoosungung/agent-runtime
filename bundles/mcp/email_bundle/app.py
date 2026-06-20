"""MCP SDK email-server bundle — list/read/send across IMAP, POP3, Outlook, Gmail.

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:mcp_sdk"
    name         = "email-server"
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

from models import EmailSettings  # noqa: E402
from providers import get_provider  # noqa: E402
from utils import normalize_recipients  # noqa: E402


def build_server(cfg: dict, secrets) -> Any:
    settings = EmailSettings.from_cfg(cfg)
    provider = get_provider(cfg, secrets)

    server = Server("email-server")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="list_messages",
                description="List messages in a mailbox folder.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Folder name (default from config).",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "default": settings.page_size,
                        },
                        "cursor": {
                            "type": "string",
                            "description": "Provider-native pagination cursor.",
                        },
                        "query": {
                            "type": "string",
                            "description": "Optional search query.",
                        },
                    },
                },
            ),
            types.Tool(
                name="read_message",
                description="Read a single message by id.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message_id": {
                            "type": "string",
                            "description": "Message id from list_messages.",
                        },
                        "include_body": {"type": "boolean", "default": True},
                        "prefer": {
                            "type": "string",
                            "enum": ["text", "html"],
                            "default": "text",
                        },
                    },
                    "required": ["message_id"],
                },
            ),
            types.Tool(
                name="send_message",
                description="Send a plain-text email.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "to": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                        },
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "cc": {"type": "array", "items": {"type": "string"}},
                        "bcc": {"type": "array", "items": {"type": "string"}},
                        "reply_to_message_id": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name == "list_messages":
            limit = int(arguments.get("limit", settings.page_size))
            limit = max(1, min(50, limit))
            result = await provider.list_messages(
                folder=arguments.get("folder"),
                limit=limit,
                cursor=arguments.get("cursor"),
                query=arguments.get("query"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "read_message":
            result = await provider.read_message(
                message_id=arguments["message_id"],
                include_body=bool(arguments.get("include_body", True)),
                prefer=str(arguments.get("prefer", "text")),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "send_message":
            to_raw = arguments["to"]
            to = normalize_recipients(to_raw)
            cc = normalize_recipients(arguments["cc"]) if arguments.get("cc") else None
            bcc = normalize_recipients(arguments["bcc"]) if arguments.get("bcc") else None
            result = await provider.send_message(
                to=to,
                subject=arguments["subject"],
                body=arguments["body"],
                cc=cc,
                bcc=bcc,
                reply_to_message_id=arguments.get("reply_to_message_id"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
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
