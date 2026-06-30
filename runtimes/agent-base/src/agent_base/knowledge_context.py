"""Per-request knowledge binding context for general agents."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar

from runtime_common.knowledge import KnowledgeBinding, resolve_knowledge_bindings

logger = logging.getLogger(__name__)

_bindings_var: ContextVar[list[KnowledgeBinding] | None] = ContextVar(
    "knowledge_bindings",
    default=None,
)


def get_current_bindings() -> list[KnowledgeBinding]:
    return _bindings_var.get() or []


def reset_knowledge_bindings(token) -> None:
    _bindings_var.reset(token)


async def setup_knowledge_bindings(
    *,
    tenant: str | None,
    project_ids: list[str],
    path_graph_dsn: str | None,
) -> object:
    """Resolve bindings for this invoke request. Returns context token for reset."""
    token = _bindings_var.set([])
    if not tenant or not project_ids or not path_graph_dsn:
        return token

    try:
        from path_graph.admin.lifecycle import api_get_binding
    except ImportError:
        logger.warning("path_graph_unavailable_for_knowledge_resolve")
        return token

    def fetch_binding(t: str, project_id: str) -> dict:
        return api_get_binding(t, project_id)

    try:
        bindings = await asyncio.to_thread(
            resolve_knowledge_bindings,
            tenant,
            project_ids,
            fetch_binding=fetch_binding,
        )
        _bindings_var.set(bindings)
    except Exception as exc:
        logger.warning(
            "knowledge_binding_resolve_failed",
            extra={"error": str(exc), "tenant": tenant, "projects": project_ids},
        )
    return token
