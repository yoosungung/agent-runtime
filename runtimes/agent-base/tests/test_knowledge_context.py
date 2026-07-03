"""Tests for per-invoke knowledge binding context."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_base.knowledge_context import (
    get_current_bindings,
    reset_knowledge_bindings,
    setup_knowledge_bindings,
)
from runtime_common.knowledge.models import KnowledgeBinding

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
BINDING_PAYLOAD = {
    "tenant": "acme",
    "project_id": PROJECT_ID,
    "project_slug": "docs",
    "rag": {
        "index_namespace": "path_graph_acme_docs",
        "filter": {"project_id": PROJECT_ID},
    },
    "graph": {"nebula_space": "path_graph_acme_docs"},
    "wiki": {"s3_prefix": "wiki/acme/x/", "vfs_mount": "/wiki/docs/"},
}


@pytest.mark.asyncio
async def test_setup_knowledge_bindings_resolves_projects():
    with patch(
        "agent_base.knowledge_context.fetch_project_binding",
        return_value=BINDING_PAYLOAD,
    ):
        token = await setup_knowledge_bindings(
            tenant="acme",
            project_ids=[PROJECT_ID],
            admin_backend_url="http://backend.test:8000",
        )
    try:
        bindings = get_current_bindings()
        assert len(bindings) == 1
        assert bindings[0].project_id == PROJECT_ID
        assert bindings[0].rag.index_namespace == "path_graph_acme_docs"
    finally:
        reset_knowledge_bindings(token)


@pytest.mark.asyncio
async def test_setup_knowledge_bindings_skips_without_backend_url():
    token = await setup_knowledge_bindings(
        tenant="acme",
        project_ids=[PROJECT_ID],
        admin_backend_url=None,
    )
    try:
        assert get_current_bindings() == []
    finally:
        reset_knowledge_bindings(token)


@pytest.mark.asyncio
async def test_setup_knowledge_bindings_tolerates_resolve_failure():
    with patch(
        "agent_base.knowledge_context.fetch_project_binding",
        side_effect=ValueError("project not found"),
    ):
        token = await setup_knowledge_bindings(
            tenant="acme",
            project_ids=[PROJECT_ID],
            admin_backend_url="http://backend.test:8000",
        )
    try:
        assert get_current_bindings() == []
    finally:
        reset_knowledge_bindings(token)


def test_binding_model_roundtrip():
    binding = KnowledgeBinding.from_api_dict(BINDING_PAYLOAD)
    assert binding.wiki.vfs_mount == "/wiki/docs/"
