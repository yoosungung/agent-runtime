"""DeepAgent research bundle — own ``think_tool`` + MCP-routed search/fetch.

Returns a ``CompiledStateGraph`` (DeepAgents wraps LangGraph). Demonstrates
the canonical "use your own reflection tool + delegate I/O to an MCP server"
pattern. The agent:
  * does its own thinking via ``think_tool`` (no LLM, no I/O — just records
    the reflection in the conversation),
  * calls Naver web search and URL fetch via ``naver_search`` / ``fetch_url``
    tools that route through the MCP server identified by
    ``cfg["mcp_server"]`` (default ``"search-server"``),
  * delegates focused topics to a ``researcher`` subagent with the same
    tool set.

JWT forwarding: the bundle uses ``agent_base.app.get_current_token()`` to
attach the caller's bearer token to outbound MCP calls so the gateway's
grace-period check can authorise the internal hop.

Deploy as:
    entrypoint   = "app:build_agent"
    runtime_pool = "agent:compiled_graph"

Bundle deps (in this bundle's ``pyproject.toml``):
    deepagents>=0.5, langchain-anthropic>=0.3, httpx>=0.27

Source config (``source_meta.config``):
    {
      "langgraph": {
        "model": "anthropic:claude-sonnet-4-6",
        "recursion_limit": 50,
        "checkpointer": "redis"
      },
      "mcp_server": "search-server",
      "anthropic_api_key": "sk-ant-..."
    }

Per-user override (``user_meta.config``):
    {"langgraph": {"model": "anthropic:claude-opus-4-7"}, "mcp_server": "other-search"}

Required secrets (DSNs only — API keys are now in cfg):
    - ``CHECKPOINTER_DSN`` — when ``cfg.langgraph.checkpointer != "none"``
    - ``STORE_DSN``        — when ``cfg.langgraph.store.backend != "none"``
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from deepagents import create_deep_agent
from langchain_core.tools import tool

from agent_base.app import get_current_token
from runtime_common.providers.langgraph import (
    build_checkpointer,
    build_store,
    get_model_spec,
)
from runtime_common.secrets import SecretResolver

_DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"
_DEFAULT_MCP_SERVER = "search-server"


def build_agent(cfg: dict, secrets: SecretResolver) -> Any:
    # init_chat_model (used by deepagents) picks up provider keys from env.
    # We export whichever cfg keys are present so any of "anthropic:...",
    # "openai:...", or "google:..." model specs work without further wiring.
    for cfg_key, env_key in (
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("google_api_key", "GOOGLE_API_KEY"),
    ):
        if val := cfg.get(cfg_key):
            os.environ[env_key] = val

    mcp_server = cfg.get("mcp_server", _DEFAULT_MCP_SERVER)
    mcp_gateway_url = os.environ["MCP_GATEWAY_URL"]

    @tool(parse_docstring=True)
    def think_tool(reflection: str) -> str:
        """Record a reflection on findings, gaps, and next steps.

        Use after each search to assess what was learned and plan the next move.
        No I/O, no LLM — purely a slot in the conversation for the model's own
        chain-of-thought.

        Args:
            reflection: Free-form notes on findings and what to look at next.
        """
        return f"Reflection recorded: {reflection}"

    @tool(parse_docstring=True)
    async def naver_search(query: str, display: int = 5) -> str:
        """Search the Korean web via Naver (routed through the MCP server).

        Args:
            query: Search query.
            display: Number of results to return (1-10, default 5).
        """
        result = await _call_mcp(
            mcp_gateway_url, mcp_server, "naver_search",
            {"query": query, "display": display},
            get_current_token(),
        )
        return _stringify(result)

    @tool(parse_docstring=True)
    async def fetch_url(url: str, timeout_seconds: float = 10.0) -> str:
        """Fetch a URL and return the body (truncated to 8 KB) via the MCP server.

        Args:
            url: Absolute http(s):// URL to fetch.
            timeout_seconds: Request timeout in seconds (default 10).
        """
        result = await _call_mcp(
            mcp_gateway_url, mcp_server, "fetch_url",
            {"url": url, "timeout_seconds": timeout_seconds},
            get_current_token(),
        )
        return _stringify(result)

    tools = [think_tool, naver_search, fetch_url]
    researcher = {
        "name": "researcher",
        "description": "Delegate one focused research topic to this subagent at a time.",
        "system_prompt": (
            "You are a focused researcher. Use naver_search to gather sources, "
            "fetch_url to read interesting links, think_tool to reflect after each step, "
            "then return a concise summary with citations."
        ),
        "tools": tools,
    }

    # NOTE: deepagents v0.5+ does not accept recursion_limit at create time; the
    # cap is applied at invoke time via RunnableConfig (set by agent-base runner).
    # ``get_recursion_limit(cfg)`` is wired through cfg → runner → invoke config.
    return create_deep_agent(
        model=get_model_spec(cfg) or _DEFAULT_MODEL,
        tools=tools,
        system_prompt=(
            "You orchestrate web research. Plan with write_todos, delegate topic-specific "
            "research to the `researcher` subagent, synthesise findings, and produce a "
            "structured final report with citations."
        ),
        subagents=[researcher],
        checkpointer=build_checkpointer(cfg, secrets),
        store=build_store(cfg, secrets),
    )


async def _call_mcp(
    gateway_url: str,
    server: str,
    tool: str,
    arguments: dict,
    token: str | None,
) -> object:
    headers = {"X-Runtime-Caller": "agent-pool"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"server": server, "tool": tool, "arguments": arguments}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{gateway_url}/v1/mcp/invoke-internal", json=payload, headers=headers
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return resp.text


def _stringify(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict | list):
        import json
        return json.dumps(obj, ensure_ascii=False)
    return str(obj)
