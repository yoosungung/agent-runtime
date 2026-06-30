"""Tests for agent delegate tool invocation."""

from __future__ import annotations

import asyncio

import pytest


def test_build_agent_delegate_tools_skipped_at_max_depth(monkeypatch):
    import agent_base.agent_tools as agent_mod

    monkeypatch.setattr(agent_mod, "get_delegate_depth", lambda: 3)
    tools = agent_mod.build_agent_delegate_tools(
        ["researcher"],
        gateway_url="http://gw",
        max_depth=3,
    )
    assert tools == []


def test_build_agent_delegate_tools_skipped_when_disabled(monkeypatch):
    import agent_base.agent_tools as agent_mod

    monkeypatch.setattr(agent_mod, "get_delegate_depth", lambda: 0)
    tools = agent_mod.build_agent_delegate_tools(
        ["researcher"],
        gateway_url="http://gw",
        allow_delegation=False,
    )
    assert tools == []


def test_delegate_tool_calls_invoke_internal(monkeypatch):
    import agent_base.agent_tools as agent_mod

    calls: list[dict] = []

    async def fake_call(gateway_url, agent, task, token, depth, timeout_sec):
        calls.append(
            {
                "gateway": gateway_url,
                "agent": agent,
                "task": task,
                "token": token,
                "depth": depth,
                "timeout": timeout_sec,
            }
        )
        return {"output": "delegate result"}

    monkeypatch.setattr(agent_mod, "get_delegate_depth", lambda: 0)
    monkeypatch.setattr(agent_mod, "get_current_token", lambda: "jwt-token")
    monkeypatch.setattr(agent_mod, "_call_agent_delegate", fake_call)

    tools = agent_mod.build_agent_delegate_tools(
        ["researcher"],
        gateway_url="http://gw",
        delegate_timeout_sec=45,
    )
    assert len(tools) == 1
    assert tools[0].name == "delegate_researcher"

    out = asyncio.run(tools[0].coroutine(task="find papers on RAG"))
    assert "delegate result" in out
    assert calls == [
        {
            "gateway": "http://gw",
            "agent": "researcher",
            "task": "find papers on RAG",
            "token": "jwt-token",
            "depth": 1,
            "timeout": 45,
        }
    ]


def test_call_agent_delegate_posts_with_headers(monkeypatch):
    import agent_base.agent_tools as agent_mod

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output": "ok"}

    class FakeClient:
        def __init__(self):
            self.last: dict | None = None

        async def post(self, url, json=None, headers=None, **kwargs):
            self.last = {"url": url, "json": json, "headers": headers}
            return FakeResponse()

    client = FakeClient()
    monkeypatch.setattr(agent_mod, "get_agent_http_client", lambda: client)

    result = asyncio.run(
        agent_mod._call_agent_delegate(
            "http://gw",
            "helper",
            "do work",
            "tok",
            depth=2,
            timeout_sec=30.0,
        )
    )
    assert result == {"output": "ok"}
    assert client.last is not None
    assert client.last["url"] == "http://gw/v1/agents/invoke-internal"
    assert client.last["json"]["agent"] == "helper"
    assert client.last["json"]["input"] == {"message": "do work"}
    assert "session_id" in client.last["json"]
    assert client.last["headers"]["Authorization"] == "Bearer tok"
    assert client.last["headers"]["X-Runtime-Caller"] == "agent-pool"
    assert client.last["headers"]["X-Runtime-Delegate-Depth"] == "2"
