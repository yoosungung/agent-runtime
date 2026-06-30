"""Agent delegate bridge tests."""

from __future__ import annotations

import asyncio

from hermes_base.agent_bridge import invoke_agent_delegate


def test_invoke_agent_delegate_posts_internal(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"output": "done"}

    class FakeClient:
        def __init__(self):
            self.last: dict | None = None

        async def post(self, url, json=None, headers=None, timeout=None):
            self.last = {"url": url, "json": json, "headers": headers}
            return FakeResponse()

    client = FakeClient()
    monkeypatch.setattr("hermes_base.agent_bridge.get_agent_http_client", lambda: client)
    monkeypatch.setattr("hermes_base.agent_bridge.get_current_token", lambda: "tok")
    monkeypatch.setattr("hermes_base.agent_bridge.get_current_delegate_depth", lambda: 0)

    result = asyncio.run(
        invoke_agent_delegate("http://envoy.test", "helper", "summarize this")
    )
    assert result == {"output": "done"}
    assert client.last is not None
    assert client.last["url"] == "http://envoy.test/v1/agents/invoke-internal"
    assert client.last["headers"]["X-Runtime-Delegate-Depth"] == "1"
