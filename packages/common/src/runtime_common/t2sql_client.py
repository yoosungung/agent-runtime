"""T2SQL (Text-to-SQL) client for MCP bundles.

Bundles that host a T2SQL-backed MCP server import and instantiate this
client rather than implementing their own HTTP layer.

Usage in a bundle factory::

    from runtime_common.t2sql_client import T2SqlClient
    from runtime_common.secrets import SecretResolver

    def factory(user_cfg: dict, secrets: SecretResolver) -> T2SqlClient:
        return T2SqlClient(
            base_url=os.environ["T2SQL_SERVICE_URL"],
            schema_hint=user_cfg.get("schema_hint", ""),
        )

The instance is consumed by mcp-base runner via ``instance.call(tool, args)``
and optionally ``instance.list_tools()``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# T2SQL standard tool names
TOOL_QUERY = "query"
TOOL_EXPLAIN = "explain"
TOOL_SCHEMA = "schema"


class T2SqlClient:
    """Async HTTP client for a Text-to-SQL backend service.

    Implements the duck-typed protocol expected by mcp-base runner:
    - ``call(tool, arguments) -> Any``
    - ``list_tools() -> list[dict]``

    Args:
        base_url:    Base URL of the T2SQL service.
        schema_hint: Default DB schema hint passed to the model.
        timeout:     HTTP timeout in seconds (NL→SQL can be slow).
        headers:     Extra headers (e.g. auth tokens).
    """

    def __init__(
        self,
        base_url: str,
        schema_hint: str = "",
        timeout: float = 60.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._schema_hint = schema_hint
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=headers or {},
        )

    async def call(self, tool: str, arguments: dict) -> Any:
        """Dispatch a tool call to the T2SQL service.

        Sends ``POST /{tool}`` with the arguments as JSON body.
        Injects ``schema_hint`` if not already present in ``arguments``.
        """
        payload = dict(arguments)
        if self._schema_hint:
            payload.setdefault("schema_hint", self._schema_hint)
        try:
            resp = await self._http.post(f"/{tool}", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "t2sql_error",
                extra={"tool": tool, "status": exc.response.status_code},
            )
            raise

    async def list_tools(self) -> list[dict]:
        """Return available tools from the T2SQL service.

        Falls back to a static list of well-known tools if the service
        does not expose a ``GET /tools`` endpoint.
        """
        try:
            resp = await self._http.get("/tools")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("tools", [])
        except Exception:
            return [
                {
                    "name": TOOL_QUERY,
                    "description": "Translate natural language to SQL and execute",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "schema_hint": {"type": "string"},
                            "max_rows": {"type": "integer", "default": 100},
                        },
                        "required": ["question"],
                    },
                },
                {
                    "name": TOOL_EXPLAIN,
                    "description": "Explain an existing SQL query in plain language",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"sql": {"type": "string"}},
                        "required": ["sql"],
                    },
                },
                {
                    "name": TOOL_SCHEMA,
                    "description": "Return the database schema",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"table_filter": {"type": "string"}},
                    },
                },
            ]

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> T2SqlClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
