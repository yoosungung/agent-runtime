"""Shared httpx client for MCP gateway calls."""

from __future__ import annotations

import httpx

_client: httpx.AsyncClient | None = None


def get_mcp_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _client


async def close_mcp_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
