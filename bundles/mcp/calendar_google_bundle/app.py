"""MCP SDK calendar-google bundle — Google Calendar API.

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:mcp_sdk"
    name         = "calendar-google"
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

from client import GoogleCalendarClient  # noqa: E402
from models import CalendarSettings  # noqa: E402
from utils import clamp_limit  # noqa: E402

_CALENDAR_TOOLS = [
    types.Tool(
        name="list_calendars",
        description="List calendars accessible to the signed-in user.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="list_events",
        description="List calendar events in a time range.",
        inputSchema={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "ISO8601 range start."},
                "time_max": {"type": "string", "description": "ISO8601 range end."},
                "calendar_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "cursor": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
        },
    ),
    types.Tool(
        name="get_event",
        description="Get a single calendar event by id.",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string"},
            },
            "required": ["event_id"],
        },
    ),
    types.Tool(
        name="find_availability",
        description="Find free/busy availability for attendees.",
        inputSchema={
            "type": "object",
            "properties": {
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
                "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
            },
            "required": ["attendees", "time_min", "time_max"],
        },
    ),
    types.Tool(
        name="create_event",
        description="Create a calendar event.",
        inputSchema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "body": {"type": "string"},
                "location": {"type": "string"},
                "calendar_id": {"type": "string"},
                "is_online_meeting": {"type": "boolean", "default": False},
            },
            "required": ["subject", "start", "end"],
        },
    ),
    types.Tool(
        name="update_event",
        description="Update a calendar event (partial patch).",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "patch": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "body": {"type": "string"},
                        "location": {"type": "string"},
                        "attendees": {"type": "array", "items": {"type": "string"}},
                        "is_online_meeting": {"type": "boolean"},
                    },
                },
            },
            "required": ["event_id", "patch"],
        },
    ),
    types.Tool(
        name="cancel_event",
        description="Cancel/delete a calendar event.",
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "calendar_id": {"type": "string"},
                "send_cancellation": {"type": "boolean", "default": True},
            },
            "required": ["event_id"],
        },
    ),
]


def build_server(cfg: dict, secrets) -> Any:
    settings = CalendarSettings.from_cfg(cfg)
    client = GoogleCalendarClient(cfg, secrets)

    server = Server("calendar-google")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return list(_CALENDAR_TOOLS)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.ContentBlock]:
        if name == "list_calendars":
            result = await client.list_calendars()
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "list_events":
            limit = clamp_limit(
                int(arguments.get("limit", settings.page_size)),
                default=settings.page_size,
            )
            result = await client.list_events(
                time_min=arguments["time_min"],
                time_max=arguments["time_max"],
                calendar_id=arguments.get("calendar_id"),
                limit=limit,
                cursor=arguments.get("cursor"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "get_event":
            result = await client.get_event(
                event_id=arguments["event_id"],
                calendar_id=arguments.get("calendar_id"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "find_availability":
            result = await client.find_availability(
                attendees=arguments["attendees"],
                time_min=arguments["time_min"],
                time_max=arguments["time_max"],
                duration_minutes=arguments.get("duration_minutes"),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "create_event":
            result = await client.create_event(
                subject=arguments["subject"],
                start=arguments["start"],
                end=arguments["end"],
                attendees=arguments.get("attendees"),
                body=arguments.get("body"),
                location=arguments.get("location"),
                calendar_id=arguments.get("calendar_id"),
                is_online_meeting=bool(arguments.get("is_online_meeting", False)),
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "update_event":
            result = await client.update_event(
                event_id=arguments["event_id"],
                patch=arguments["patch"],
            )
            return [types.TextContent(type="text", text=json.dumps(result.to_dict()))]
        if name == "cancel_event":
            result = await client.cancel_event(
                event_id=arguments["event_id"],
                calendar_id=arguments.get("calendar_id"),
                send_cancellation=bool(arguments.get("send_cancellation", True)),
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
