"""Resolve pipeline knowledge bindings."""

from __future__ import annotations

from collections.abc import Callable

from runtime_common.knowledge.models import KnowledgeBinding


def resolve_knowledge_bindings(
    tenant: str,
    project_ids: list[str],
    *,
    fetch_binding: Callable[[str, str], dict],
) -> list[KnowledgeBinding]:
    """Resolve bindings for each project id using the injected fetcher."""
    bindings: list[KnowledgeBinding] = []
    for project_id in project_ids:
        raw = fetch_binding(tenant, project_id)
        binding = KnowledgeBinding.from_api_dict(raw)
        if binding.tenant and binding.tenant != tenant:
            raise ValueError(f"binding tenant mismatch for project {project_id}")
        bindings.append(binding)
    return bindings
