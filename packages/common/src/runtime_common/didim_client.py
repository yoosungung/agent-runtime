"""DidimRAG client for MCP bundles.

Bundles that host a DidimRAG-backed MCP server import and instantiate this
client rather than implementing their own HTTP layer.

Usage in a bundle factory::

    from runtime_common.didim_client import DidimRagClient
    from runtime_common.secrets import SecretResolver

    def factory(user_cfg: dict, secrets: SecretResolver) -> DidimRagClient:
        return DidimRagClient(
            base_url=os.environ["DIDIM_RAG_URL"],
            collection=user_cfg.get("collection", "default"),
        )

The instance is consumed by mcp-base runner via ``instance.call(tool, args)``
and optionally ``instance.list_tools()``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# DidimRAG standard tool names
TOOL_SEARCH = "search"
TOOL_EMBED = "embed"
TOOL_INDEX = "index"


class DidimRagClient:
    """Async HTTP client for a DidimRAG backend service.

    Implements the duck-typed protocol expected by mcp-base runner:
    - ``call(tool, arguments) -> Any``
    - ``list_tools() -> list[dict]``

    Args:
        base_url:   Base URL of the DidimRAG service.
        collection: Default vector collection name (overridable per-call).
        timeout:    HTTP timeout in seconds.
        headers:    Extra headers (e.g. auth tokens).
    """

    def __init__(
        self,
        base_url: str,
        collection: str = "default",
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._collection = collection
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers=headers or {},
        )

    async def call(self, tool: str, arguments: dict) -> Any:
        """Dispatch a tool call to the DidimRAG service.

        Sends ``POST /{tool}`` with the arguments as JSON body.
        The ``collection`` argument defaults to the instance's collection if
        not provided in ``arguments``.
        """
        payload = dict(arguments)
        payload.setdefault("collection", self._collection)
        try:
            resp = await self._http.post(f"/{tool}", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "didim_rag_error",
                extra={"tool": tool, "status": exc.response.status_code},
            )
            raise

    async def list_tools(self) -> list[dict]:
        """Return available tools from the DidimRAG service.

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
                    "name": TOOL_SEARCH,
                    "description": "Semantic search over the vector collection",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "default": 5},
                            "collection": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": TOOL_EMBED,
                    "description": "Embed text and return vector",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            ]

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> DidimRagClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
