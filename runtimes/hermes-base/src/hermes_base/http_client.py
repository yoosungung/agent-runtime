"""Shared httpx client for MCP gateway calls."""

from __future__ import annotations

import httpx

_mcp_client: httpx.AsyncClient | None = None
_agent_client: httpx.AsyncClient | None = None


def get_mcp_http_client() -> httpx.AsyncClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _mcp_client


def get_agent_http_client() -> httpx.AsyncClient:
    global _agent_client
    if _agent_client is None:
        _agent_client = httpx.AsyncClient(
            timeout=60.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _agent_client


async def close_mcp_http_client() -> None:
    global _mcp_client, _agent_client
    if _mcp_client is not None:
        await _mcp_client.aclose()
        _mcp_client = None
    if _agent_client is not None:
        await _agent_client.aclose()
        _agent_client = None
