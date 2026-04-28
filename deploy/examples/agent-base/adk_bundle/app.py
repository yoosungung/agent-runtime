"""Google ADK research-and-math bundle — ``calculate`` (own) + MCP-routed search/fetch.

Returns an ``LlmAgent`` (alias ``Agent``) wired to Gemini with three tools:
  * ``calculate(expression)`` — own bundle tool, safe arithmetic via ast walker
  * ``naver_search(query)`` — routed through the MCP server identified by
    ``cfg["mcp_server"]``
  * ``fetch_url(url)`` — routed through the same MCP server

Demonstrates the canonical ADK pattern: ``LlmAgent`` + ``GenerateContentConfig``
+ a mix of pure-Python tools and tools that delegate to external MCP services.
``agent_base`` builds the ``Runner`` (with session/memory services) — the
bundle returns just the agent.

Deploy as:
    entrypoint   = "app:build_agent"
    runtime_pool = "agent:adk"

Bundle deps: uses google-adk + httpx (both already in agent-base image).

Source config (``source_meta.config``):
    {
      "adk": {
        "model": "google:gemini-2.0-flash",
        "temperature": 0.0,
        "max_output_tokens": 4096
      },
      "mcp_server": "search-server",
      "google_api_key": "AIza..."
    }

Per-user override (``user_meta.config``):
    {"adk": {"model": "google:gemini-2.5-flash"}, "mcp_server": "other-search"}
"""

from __future__ import annotations

import ast
import operator as op
import os
from typing import Any

import httpx
from google.adk import Agent
from google.genai import types

from agent_base.app import get_current_token
from runtime_common.providers.adk import build_generate_content_config, get_model
from runtime_common.secrets import SecretResolver

_DEFAULT_MCP_SERVER = "search-server"

_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow,
}
_UNARYOPS = {ast.UAdd: op.pos, ast.USub: op.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _resolve_model(model_spec: str) -> Any:
    """Map a ``provider:model`` spec to the right ADK model representation.

    - ``google:gemini-...`` → bare string ``gemini-...`` (ADK native)
    - ``openai:...`` / ``anthropic:...`` → ``LiteLlm("provider/model")`` wrapper
    - no prefix → bare string (assumes Gemini)
    """
    if ":" not in model_spec:
        return model_spec
    provider, name = model_spec.split(":", 1)
    if provider == "google":
        return name
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=f"{provider}/{name}")


def build_agent(cfg: dict, secrets: SecretResolver) -> Any:  # noqa: ARG001 — secrets unused
    # Export whichever provider keys are present so LiteLlm + ADK pick them up.
    for cfg_key, env_key in (
        ("google_api_key", "GOOGLE_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    ):
        if val := cfg.get(cfg_key):
            os.environ[env_key] = val

    mcp_server = cfg.get("mcp_server", _DEFAULT_MCP_SERVER)
    mcp_gateway_url = os.environ["MCP_GATEWAY_URL"]

    def calculate(expression: str) -> float:
        """Evaluate a basic arithmetic expression.

        Supports +, -, *, /, //, %, ** and unary +/-. No names or function calls.
        Example: calculate("(3 + 4) * 2 ** 3") returns 56.0.

        Args:
            expression: Arithmetic expression to evaluate.

        Returns:
            The numeric result as a float.
        """
        try:
            return float(_safe_eval(ast.parse(expression, mode="eval").body))
        except (ValueError, SyntaxError, ZeroDivisionError) as exc:
            raise ValueError(f"could not evaluate {expression!r}: {exc}") from exc

    async def naver_search(query: str, display: int = 5) -> str:
        """Search the Korean web via Naver (routed through the MCP server).

        Args:
            query: Search query.
            display: Number of results (1-10, default 5).
        """
        result = await _call_mcp(
            mcp_gateway_url, mcp_server, "naver_search",
            {"query": query, "display": display},
            get_current_token(),
        )
        return _stringify(result)

    async def fetch_url(url: str, timeout_seconds: float = 10.0) -> str:
        """Fetch a URL and return the body (truncated to 8 KB) via the MCP server.

        Args:
            url: Absolute http(s):// URL.
            timeout_seconds: Request timeout (default 10).
        """
        result = await _call_mcp(
            mcp_gateway_url, mcp_server, "fetch_url",
            {"url": url, "timeout_seconds": timeout_seconds},
            get_current_token(),
        )
        return _stringify(result)

    gen_config = build_generate_content_config(cfg)
    gen_config.safety_settings = [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.OFF,
        ),
    ]

    return Agent(
        name="research_math_agent",
        model=_resolve_model(get_model(cfg)),
        description="Answers questions using arithmetic, web search, and URL fetch.",
        instruction=(
            "You answer user questions. Use calculate for math, naver_search to "
            "look things up on the Korean web, and fetch_url to read pages whose "
            "links you find. Combine results into a concise final answer with "
            "any citations or computation steps."
        ),
        tools=[calculate, naver_search, fetch_url],
        generate_content_config=gen_config,
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
