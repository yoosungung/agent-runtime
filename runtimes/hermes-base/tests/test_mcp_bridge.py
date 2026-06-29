"""MCP bridge tests — Envoy invoke-internal (TDD)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_base.context import get_current_token, reset_current_token, set_current_token
from hermes_base.mcp_bridge import build_runtime_mcp_env, invoke_mcp_tool
from hermes_base.schemas import McpToolManifestEntry


@pytest.mark.asyncio()
async def test_invoke_mcp_tool_forwards_jwt() -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_resp)

    tok = set_current_token("jwt-abc")
    try:
        with patch("hermes_base.mcp_bridge.get_mcp_http_client", return_value=client):
            result = await invoke_mcp_tool(
                "http://envoy.test",
                server="search",
                tool="naver_search",
                arguments={"q": "hermes"},
            )
    finally:
        reset_current_token(tok)

    assert result == {"ok": True}
    call = client.post.call_args
    assert call.args[0] == "http://envoy.test/v1/mcp/invoke-internal"
    assert call.kwargs["headers"]["Authorization"] == "Bearer jwt-abc"
    assert call.kwargs["headers"]["X-Runtime-Caller"] == "agent-pool"
    assert call.kwargs["json"] == {
        "server": "search",
        "tool": "naver_search",
        "arguments": {"q": "hermes"},
    }


@pytest.mark.asyncio()
async def test_invoke_mcp_tool_explicit_token() -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "plain"
    mock_resp.json.side_effect = ValueError()
    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_resp)

    with patch("hermes_base.mcp_bridge.get_mcp_http_client", return_value=client):
        result = await invoke_mcp_tool(
            "http://envoy.test/",
            server="s",
            tool="t",
            arguments={},
            token="explicit",
        )
    assert result == "plain"
    assert get_current_token() is None


def test_build_runtime_mcp_env_sets_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUNTIME_MCP_GATEWAY_URL", raising=False)
    monkeypatch.delenv("RUNTIME_MCP_TOOLS_JSON", raising=False)
    tools = [
        McpToolManifestEntry(server="s", name="t", description="desc"),
    ]
    build_runtime_mcp_env("http://gw", tools)
    import os

    assert os.environ["RUNTIME_MCP_GATEWAY_URL"] == "http://gw"
    payload = json.loads(os.environ["RUNTIME_MCP_TOOLS_JSON"])
    assert payload[0]["server"] == "s"
