"""Tests for scoped MCP tool invocation."""

from __future__ import annotations

import asyncio

from runtime_common.knowledge.models import KnowledgeBinding


def test_build_mcp_tools_scopes_search_collection(monkeypatch):
    import agent_base.mcp_tools as mcp_mod

    calls: list[dict] = []

    async def fake_call_mcp(gateway, server, tool, arguments, token):
        calls.append({"server": server, "tool": tool, "arguments": arguments})
        return {"results": [{"id": "1", "text": "ok"}]}

    monkeypatch.setattr(mcp_mod, "get_mcp_http_client", lambda: object())
    monkeypatch.setattr(mcp_mod, "_call_mcp", fake_call_mcp)

    binding = KnowledgeBinding.from_api_dict(
        {
            "tenant": "acme",
            "project_id": "p1",
            "rag": {"qdrant_collection": "allowed-col", "filter": {"project_id": "p1"}},
            "graph": {"nebula_space": "g1"},
            "wiki": {"s3_prefix": "w", "vfs_mount": "/wiki/w/"},
        }
    )
    monkeypatch.setattr(mcp_mod, "get_current_bindings", lambda: [binding])

    tools = mcp_mod.build_mcp_tools(
        [{"server": "rag", "name": "search", "description": ""}],
        gateway_url="http://gw",
        mcp_requires_knowledge={"rag"},
    )

    async def run_tool() -> str:
        return await tools[0].coroutine({"query": "hi", "collection": "evil"})

    out = asyncio.run(run_tool())
    assert "ok" in out
    assert calls[0]["arguments"]["collection"] == "allowed-col"
