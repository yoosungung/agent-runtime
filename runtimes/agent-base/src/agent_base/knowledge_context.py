"""Per-request knowledge binding context for general agents."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar

from runtime_common.knowledge import KnowledgeBinding, resolve_knowledge_bindings
from runtime_common.pipeline_binding import fetch_project_binding

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
    admin_backend_url: str | None,
) -> object:
    """Resolve bindings for this invoke request. Returns context token for reset."""
    token = _bindings_var.set([])
    if not tenant or not project_ids or not admin_backend_url:
        return token

    def fetch_binding(t: str, project_id: str) -> dict:
        return fetch_project_binding(admin_backend_url, t, project_id)

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
