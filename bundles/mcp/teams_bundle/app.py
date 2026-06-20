"""MCP SDK teams-server bundle — Microsoft Teams via Graph.

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:mcp_sdk"
    name         = "teams-server"
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

from client import GraphTeamsClient  # noqa: E402
from models import TeamsSettings  # noqa: E402
from utils import clamp_limit  # noqa: E402


def build_server(cfg: dict, secrets) -> Any:
    settings = TeamsSettings.from_cfg(cfg)
    client = GraphTeamsClient(cfg, secrets)

    server = Server("teams-server")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="list_joined_teams",
                description="List Microsoft Teams the signed-in user has joined.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="list_channels",
                description="List channels in a team.",
                inputSchema={
                    "type": "object",
                    "properties": {"team_id": {"type": "string"}},
                },
            ),
            types.Tool(
                name="list_chats",
                description="List 1:1 and group chats for the signed-in user.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "cursor": {"type": "string"},
                        "expand_members": {"type": "boolean", "default": False},
                    },
                },
            ),
            types.Tool(
                name="list_channel_messages",
                description="List recent messages in a team channel.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_id": {"type": "string"},
                        "channel_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "cursor": {"type": "string"},
                    },
                },
            ),
            types.Tool(
                name="list_chat_messages",
                description="List recent messages in a chat.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "cursor": {"type": "string"},
                    },
                    "required": ["chat_id"],
                },
            ),
            types.Tool(
                name="send_channel_message",
                description="Send a message to a team channel.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "team_id": {"type": "string"},
                        "channel_id": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {
                            "type": "string",
                            "enum": ["text", "html"],
                            "default": "text",
                        },
                    },
                    "required": ["content"],
                },
            ),
            types.Tool(
                name="send_chat_message",
                description="Send a message to a 1:1 or group chat.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chat_id": {"type": "string"},
                        "content": {"type": "string"},
                        "content_type": {
                            "type": "string",
                            "enum": ["text", "html"],
                            "default": "text",
                        },
                    },
                    "required": ["chat_id", "content"],
                },
            ),
            types.Tool(
                name="create_chat",
                description="Create a 1:1 chat with another user.",
                inputSchema={
                    "type": "object",
                    "properties": {"member_user_id": {"type": "string"}},
                    "required": ["member_user_id"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name == "list_joined_teams":
            result = await client.list_joined_teams()
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "list_channels":
            result = await client.list_channels(team_id=arguments.get("team_id"))
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "list_chats":
            limit = clamp_limit(
                int(arguments.get("limit", settings.page_size)),
                default=settings.page_size,
            )
            result = await client.list_chats(
                limit=limit,
                cursor=arguments.get("cursor"),
                expand_members=bool(arguments.get("expand_members", False)),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "list_channel_messages":
            limit = clamp_limit(
                int(arguments.get("limit", settings.page_size)),
                default=settings.page_size,
            )
            result = await client.list_channel_messages(
                team_id=arguments.get("team_id"),
                channel_id=arguments.get("channel_id"),
                limit=limit,
                cursor=arguments.get("cursor"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "list_chat_messages":
            limit = clamp_limit(
                int(arguments.get("limit", settings.page_size)),
                default=settings.page_size,
            )
            result = await client.list_chat_messages(
                chat_id=arguments["chat_id"],
                limit=limit,
                cursor=arguments.get("cursor"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "send_channel_message":
            result = await client.send_channel_message(
                team_id=arguments.get("team_id"),
                channel_id=arguments.get("channel_id"),
                content=arguments["content"],
                content_type=str(arguments.get("content_type", "text")),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "send_chat_message":
            result = await client.send_chat_message(
                chat_id=arguments["chat_id"],
                content=arguments["content"],
                content_type=str(arguments.get("content_type", "text")),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "create_chat":
            result = await client.create_chat(member_user_id=arguments["member_user_id"])
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
