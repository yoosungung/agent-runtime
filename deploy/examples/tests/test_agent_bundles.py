"""Tests for the agent-base example bundles.

Both agent bundles call the MCP server through ``MCP_GATEWAY_URL`` — the tests
patch ``httpx.AsyncClient`` on the bundle module to capture the outbound
request without hitting the network. Real LLM calls are not exercised; the
tests pin the factory wiring (own tools registered, MCP-routed tools forward
the JWT correctly, recursion/temperature cfg propagates).
"""

from __future__ import annotations

import os

import pytest

# MCP_GATEWAY_URL is required by both bundles at build time.
os.environ.setdefault("MCP_GATEWAY_URL", "http://mcp-gateway.test")


@pytest.fixture
def secrets():
    from runtime_common.secrets import EnvSecretResolver

    return EnvSecretResolver()


# Recording httpx stub — both bundles use ``httpx.AsyncClient`` for MCP calls.

class _FakeResp:
    def __init__(self, body: object) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._body


class _FakeClient:
    last_call: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict) -> _FakeResp:
        type(self).last_call = {"url": url, "json": json, "headers": headers}
        # Mimic an MCP tool result envelope.
        return _FakeResp({"result": {"echoed": json["arguments"]}})


@pytest.fixture
def fake_httpx(monkeypatch):
    def _patch(module):
        monkeypatch.setattr(module.httpx, "AsyncClient", _FakeClient, raising=True)
        _FakeClient.last_call = {}
        return _FakeClient

    return _patch


# ────────────────────────────────────────────────────────────────────────────
# compiled_graph_bundle (DeepAgents — think + MCP-routed search/fetch_url)
# ────────────────────────────────────────────────────────────────────────────


class TestCompiledGraphBundle:
    def test_factory_returns_compiled_graph(self, load_bundle, secrets):
        pytest.importorskip("deepagents")

        mod = load_bundle("agent-base/compiled_graph_bundle", "cg_bundle")
        cfg = {
            "langgraph": {"model": "anthropic:claude-sonnet-4-6"},
            "anthropic_api_key": "sk-ant-test",
            "mcp_server": "search-server",
        }
        graph = mod.build_agent(cfg, secrets)

        from langgraph.graph.state import CompiledStateGraph

        assert isinstance(graph, CompiledStateGraph)

    def test_checkpointer_none_yields_no_saver(self, load_bundle, secrets):
        pytest.importorskip("deepagents")

        mod = load_bundle("agent-base/compiled_graph_bundle", "cg_bundle")
        cfg = {"langgraph": {"checkpointer": "none"}, "anthropic_api_key": "sk-ant-test"}
        graph = mod.build_agent(cfg, secrets)
        assert graph.checkpointer is None

    def test_default_recursion_limit_is_deepagent_default(self, load_bundle, secrets):
        # DeepAgents bakes recursion_limit=9999 at compile time. Per-invoke
        # overrides are applied by agent-base via RunnableConfig — not at
        # build time — so we just verify the default carries through here.
        pytest.importorskip("deepagents")

        mod = load_bundle("agent-base/compiled_graph_bundle", "cg_bundle")
        graph = mod.build_agent({"anthropic_api_key": "k"}, secrets)
        assert (graph.config or {}).get("recursion_limit") == 9999


# Direct unit test of the MCP-forwarding helper — the in-closure tool wrappers
# in compiled_graph_bundle are not externally introspectable, but they all
# delegate to ``_call_mcp`` which is module-level and exercise-able directly.


class TestCompiledGraphMcpForwarding:
    async def test_call_mcp_forwards_jwt_and_payload(self, load_bundle, fake_httpx):
        pytest.importorskip("deepagents")
        mod = load_bundle("agent-base/compiled_graph_bundle", "cg_bundle")
        client = fake_httpx(mod)

        result = await mod._call_mcp(
            "http://mcp-gateway.test", "search-server", "naver_search",
            {"query": "서울 날씨", "display": 3}, "user.jwt.token",
        )

        assert client.last_call["url"] == "http://mcp-gateway.test/v1/mcp/invoke-internal"
        assert client.last_call["json"] == {
            "server": "search-server",
            "tool": "naver_search",
            "arguments": {"query": "서울 날씨", "display": 3},
        }
        assert client.last_call["headers"]["X-Runtime-Caller"] == "agent-pool"
        assert client.last_call["headers"]["Authorization"] == "Bearer user.jwt.token"
        assert result == {"result": {"echoed": {"query": "서울 날씨", "display": 3}}}

    async def test_call_mcp_omits_auth_header_when_no_token(self, load_bundle, fake_httpx):
        pytest.importorskip("deepagents")
        mod = load_bundle("agent-base/compiled_graph_bundle", "cg_bundle")
        client = fake_httpx(mod)

        await mod._call_mcp(
            "http://mcp-gateway.test", "search-server", "fetch_url",
            {"url": "https://example.com"}, None,
        )
        assert "Authorization" not in client.last_call["headers"]


# ────────────────────────────────────────────────────────────────────────────
# adk_bundle (LlmAgent — calculate + MCP-routed search/fetch_url)
# ────────────────────────────────────────────────────────────────────────────


class TestAdkBundle:
    def test_factory_returns_llm_agent(self, load_bundle, secrets):
        from google.adk.agents import LlmAgent

        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent(
            {"adk": {"model": "google:gemini-2.0-flash"}, "google_api_key": "AIza-test"},
            secrets,
        )
        assert isinstance(agent, LlmAgent)
        assert agent.name == "research_math_agent"
        assert agent.model == "gemini-2.0-flash"  # provider prefix stripped

    def test_three_tools_registered(self, load_bundle, secrets):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent({"google_api_key": "AIza-test"}, secrets)
        tool_names = {t.name if hasattr(t, "name") else t.__name__ for t in agent.tools}
        assert tool_names == {"calculate", "naver_search", "fetch_url"}

    def test_calculate_tool_evaluates_expression(self, load_bundle, secrets):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent({"google_api_key": "AIza-test"}, secrets)
        calc = next(t for t in agent.tools if getattr(t, "__name__", "") == "calculate")
        assert calc("(3 + 4) * 2 ** 3") == 56.0

    def test_calculate_rejects_unsupported_nodes(self, load_bundle, secrets):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent({"google_api_key": "AIza-test"}, secrets)
        calc = next(t for t in agent.tools if getattr(t, "__name__", "") == "calculate")
        with pytest.raises(ValueError, match="could not evaluate"):
            calc("__import__('os')")

    async def test_naver_search_tool_calls_mcp_with_jwt(
        self, load_bundle, secrets, fake_httpx
    ):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        client = fake_httpx(mod)

        token_var = mod.get_current_token.__globals__["_current_token"]
        tok = token_var.set("user.jwt.token")
        try:
            agent = mod.build_agent(
                {"mcp_server": "search-server", "google_api_key": "AIza-test"},
                secrets,
            )
            search = next(
                t for t in agent.tools if getattr(t, "__name__", "") == "naver_search"
            )
            result = await search("서울 날씨", 3)
        finally:
            token_var.reset(tok)

        assert client.last_call["url"] == "http://mcp-gateway.test/v1/mcp/invoke-internal"
        assert client.last_call["json"] == {
            "server": "search-server",
            "tool": "naver_search",
            "arguments": {"query": "서울 날씨", "display": 3},
        }
        assert client.last_call["headers"]["Authorization"] == "Bearer user.jwt.token"
        assert "echoed" in result

    def test_generate_content_config_applied(self, load_bundle, secrets):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent(
            {"adk": {"temperature": 0.4, "max_output_tokens": 1024}, "google_api_key": "k"},
            secrets,
        )
        gc = agent.generate_content_config
        assert gc.temperature == 0.4
        assert gc.max_output_tokens == 1024

    def test_user_override_strips_provider_prefix(self, load_bundle, secrets):
        mod = load_bundle("agent-base/adk_bundle", "adk_bundle")
        agent = mod.build_agent(
            {"adk": {"model": "google:gemini-2.5-flash"}, "google_api_key": "k"},
            secrets,
        )
        assert agent.model == "gemini-2.5-flash"
