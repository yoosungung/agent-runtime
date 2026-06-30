"""Knowledge policy helpers."""

from __future__ import annotations

RETRIEVAL_TOOL_NAMES = frozenset(
    {
        "search",
        "embed",
        "semantic_search",
        "graph_context",
        "cypher_query",
        "search_vertices",
        "get_neighbors",
    }
)


def mcp_requires_knowledge_project(config: dict | None) -> bool:
    """Return whether an MCP source_meta config declares pipeline project binding."""
    if not config:
        return False
    knowledge = config.get("knowledge")
    if not isinstance(knowledge, dict):
        return False
    return bool(knowledge.get("requires_project"))


def is_retrieval_tool(tool_name: str) -> bool:
    return tool_name in RETRIEVAL_TOOL_NAMES
