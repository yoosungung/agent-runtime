"""MCP argument scoping and multi-project retrieval orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from runtime_common.knowledge.models import KnowledgeBinding
from runtime_common.knowledge.policy import is_retrieval_tool
from runtime_common.knowledge.rrf import reciprocal_rank_fusion


class KnowledgeScopeError(Exception):
    """Raised when a knowledge-scoped MCP call violates project boundaries."""


def ensure_bindings_for_server(
    server: str,
    *,
    requires_knowledge: bool,
    bindings: list[KnowledgeBinding],
) -> None:
    if requires_knowledge and not bindings:
        raise KnowledgeScopeError(
            f"MCP server '{server}' requires pipeline project binding but none configured"
        )


def scope_search_arguments(
    arguments: dict[str, Any],
    binding: KnowledgeBinding,
) -> dict[str, Any]:
    """Overwrite retrieval args with binding-derived index namespace and filters."""
    scoped = dict(arguments)
    scoped["index_namespace"] = binding.rag.index_namespace
    filters = dict(binding.rag.filter)
    filters.setdefault("project_id", binding.project_id)
    scoped["filter"] = filters
    scoped["tenant"] = binding.tenant
    scoped["project_id"] = binding.project_id
    scoped["project_slug"] = binding.project_slug
    scoped["nebula_space"] = binding.graph.nebula_space
    return scoped


def _normalize_search_results(payload: Any, *, project_id: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("results") or payload.get("hits") or payload.get("items") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        return []
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if isinstance(row, dict):
            item = dict(row)
        else:
            item = {"content": row}
        item.setdefault("id", item.get("chunk_id") or item.get("id") or f"{project_id}:{idx}")
        item["project_id"] = project_id
        out.append(item)
    return out


async def invoke_scoped_retrieval(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    bindings: list[KnowledgeBinding],
    call_mcp: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> Any:
    """Parallel per-project retrieval with RRF merge for search-like tools."""
    if not is_retrieval_tool(tool_name):
        if bindings:
            return await call_mcp(tool_name, scope_search_arguments(arguments, bindings[0]))
        return await call_mcp(tool_name, arguments)

    if not bindings:
        return await call_mcp(tool_name, arguments)

    if tool_name == "search" and len(bindings) > 1:
        async def _one(binding: KnowledgeBinding) -> list[dict[str, Any]]:
            payload = await call_mcp(tool_name, scope_search_arguments(arguments, binding))
            return _normalize_search_results(payload, project_id=binding.project_id)

        lists = await asyncio.gather(*[_one(b) for b in bindings])
        merged = reciprocal_rank_fusion(lists)
        return {"results": merged, "project_count": len(bindings)}

    return await call_mcp(tool_name, scope_search_arguments(arguments, bindings[0]))
