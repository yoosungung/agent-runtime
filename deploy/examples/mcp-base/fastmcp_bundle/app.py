"""FastMCP utility-server bundle — calculator + HTTP fetch.

Returns a ``FastMCP`` instance with two tools:
  * ``calculate(expression)`` — evaluates a constrained arithmetic expression
  * ``fetch_url(url, timeout)`` — fetches a URL and returns the text body

This is the canonical "useful but small" MCP server: pure-Python tool +
external I/O tool. Tool schemas are auto-generated from type hints.

Deploy as:
    entrypoint   = "app:build_server"
    runtime_pool = "mcp:fastmcp"

Bundle deps (declared in this bundle's ``pyproject.toml``):
    fastmcp>=3.0, httpx>=0.27

Source config (``source_meta.config``):
    {
        "fastmcp": {
            "strict_input_validation": true,
            "mask_error_details": true,
            "list_page_size": 50
        }
    }

Per-user override: FastMCP has no meaningful per-principal runtime knobs.
"""

from __future__ import annotations

import ast
import operator as op

import httpx
from fastmcp import FastMCP

from runtime_common.providers.fastmcp import apply_task_queue_env, build_server_kwargs
from runtime_common.secrets import SecretResolver

# Whitelist of operators allowed in calculate() — anything else raises.
_BINOPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
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


def build_server(cfg: dict, secrets: SecretResolver) -> FastMCP:
    apply_task_queue_env(cfg, secrets)

    mcp = FastMCP(
        name="utility-server",
        instructions="A small utility server: arithmetic calculator and HTTP fetcher.",
        **build_server_kwargs(cfg, secrets),
    )

    @mcp.tool
    def calculate(expression: str) -> float:
        """Evaluate a basic arithmetic expression.

        Supports +, -, *, /, //, %, ** and unary +/-. No names or function calls allowed.
        Example: ``calculate("(3 + 4) * 2 ** 3")`` → ``56.0``.
        """
        try:
            return float(_safe_eval(ast.parse(expression, mode="eval").body))
        except (ValueError, SyntaxError, ZeroDivisionError) as exc:
            raise ValueError(f"could not evaluate {expression!r}: {exc}") from exc

    @mcp.tool
    async def fetch_url(url: str, timeout_seconds: float = 10.0) -> str:
        """Fetch a URL via HTTP GET and return the response body as text.

        Returns the response body truncated to 8 KB to keep tool output bounded.
        """
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text[:8192]

    return mcp
