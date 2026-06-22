"""Tests for general-tier agent factory."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MCP_GATEWAY_URL", "http://mcp-gateway.test")


@pytest.fixture(autouse=True)
def _shared_postgres_checkpointer():
    pytest.importorskip("langgraph")
    from langgraph.checkpoint.memory import MemorySaver

    from runtime_common.providers import pg_infra

    pg_infra.reset_registry()
    pg_infra.set_shared_checkpointer(MemorySaver())
    yield
    pg_infra.reset_registry()


@pytest.fixture
def secrets():
    from runtime_common.secrets import EnvSecretResolver

    return EnvSecretResolver()


@pytest.fixture
def vfs_stores():
    from runtime_common.vfs.store import MemoryAgentVfsStore, MemoryUserVfsStore

    return MemoryAgentVfsStore(), MemoryUserVfsStore()


class TestBuildGeneralAgent:
    def test_builds_compiled_graph(self, secrets, vfs_stores, monkeypatch):
        pytest.importorskip("deepagents")
        agent_store, user_store = vfs_stores

        class _FakeClient:
            async def post(self, url, *, json, headers):
                class _R:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"ok": True}

                return _R()

        import agent_base.mcp_tools as mcp_mod

        monkeypatch.setattr(mcp_mod, "get_mcp_http_client", lambda: _FakeClient())

        from agent_base.general_agent import build_general_agent

        cfg = {
            "general": {
                "system_prompt": "You research things.",
                "mcp_servers": ["search-server"],
                "mcp_tools": [
                    {
                        "server": "search-server",
                        "name": "naver_search",
                        "description": "Search the web",
                    }
                ],
            },
            "langgraph": {"model": "anthropic:claude-sonnet-4-6"},
            "anthropic_api_key": "sk-ant-test",
        }
        graph = build_general_agent(
            cfg,
            secrets,
            kind="agent",
            agent_name="research-bot",
            user_id=1,
            agent_store=agent_store,
            user_store=user_store,
            mcp_gateway_url="http://mcp-gateway.test",
        )
        assert graph is not None
        assert hasattr(graph, "ainvoke")

    def test_uses_platform_default_model_when_unspecified(
        self, secrets, vfs_stores, monkeypatch
    ):
        pytest.importorskip("deepagents")
        agent_store, user_store = vfs_stores
        monkeypatch.setenv("DEFAULT_LLM_MODEL", "openai:gpt-5.4-nano")

        import agent_base.mcp_tools as mcp_mod

        monkeypatch.setattr(mcp_mod, "build_mcp_tools", lambda *a, **k: [])

        captured: dict[str, object] = {}

        def fake_create_deep_agent(*, model, **kwargs):
            captured["model"] = model
            return object()

        import agent_base.general_agent as ga_mod

        monkeypatch.setattr(ga_mod, "create_deep_agent", fake_create_deep_agent)
        monkeypatch.setattr(ga_mod, "build_checkpointer", lambda *a, **k: None)

        ga_mod.build_general_agent(
            {
                "general": {
                    "system_prompt": "Hi",
                    "mcp_servers": ["s"],
                    "mcp_tools": [{"server": "s", "name": "t", "description": ""}],
                }
            },
            secrets,
            kind="agent",
            agent_name="bot",
            user_id=1,
            agent_store=agent_store,
            user_store=user_store,
        )
        model = captured["model"]
        assert getattr(model, "model_name", None) == "gpt-5.4-nano"
        assert getattr(model, "use_responses_api", None) is False

    def test_requires_general_section(self, secrets, vfs_stores):
        from agent_base.general_agent import build_general_agent

        agent_store, user_store = vfs_stores
        with pytest.raises(ValueError, match="system_prompt"):
            build_general_agent(
                {},
                secrets,
                kind="agent",
                agent_name="x",
                user_id=1,
                agent_store=agent_store,
                user_store=user_store,
            )
