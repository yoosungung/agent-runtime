"""Tests for knowledge helpers."""

from __future__ import annotations

import pytest

from runtime_common.knowledge.models import KnowledgeBinding
from runtime_common.knowledge.policy import mcp_requires_knowledge_project
from runtime_common.knowledge.rrf import reciprocal_rank_fusion
from runtime_common.knowledge.scope import invoke_scoped_retrieval, scope_search_arguments


def test_mcp_requires_knowledge_project():
    assert mcp_requires_knowledge_project({}) is False
    assert mcp_requires_knowledge_project({"knowledge": {"requires_project": True}}) is True


def test_scope_search_arguments_overwrites_collection():
    binding = KnowledgeBinding.from_api_dict(
        {
            "tenant": "acme",
            "project_id": "p1",
            "rag": {"qdrant_collection": "col-a", "filter": {"project_id": "p1"}},
            "graph": {"nebula_space": "space-a"},
            "wiki": {"s3_prefix": "wiki/a", "vfs_mount": "/wiki/a/"},
        }
    )
    scoped = scope_search_arguments({"query": "x", "collection": "evil"}, binding)
    assert scoped["collection"] == "col-a"
    assert scoped["project_id"] == "p1"
    assert scoped["nebula_space"] == "space-a"


def test_reciprocal_rank_fusion_merges_lists():
    merged = reciprocal_rank_fusion(
        [
            [{"id": "a", "score": 0.9}, {"id": "b"}],
            [{"id": "b", "score": 0.8}, {"id": "c"}],
        ],
        top_n=3,
    )
    ids = [row["id"] for row in merged]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_invoke_scoped_retrieval_parallel_search():
    calls: list[dict] = []

    async def fake_call(_tool: str, args: dict) -> dict:
        calls.append(args)
        return {"results": [{"id": args["project_id"], "text": "hit"}]}

    bindings = [
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "t",
                "project_id": "p1",
                "rag": {"qdrant_collection": "c1", "filter": {}},
                "graph": {"nebula_space": "g1"},
                "wiki": {"s3_prefix": "w1", "vfs_mount": "/wiki/p1/"},
            }
        ),
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "t",
                "project_id": "p2",
                "rag": {"qdrant_collection": "c2", "filter": {}},
                "graph": {"nebula_space": "g2"},
                "wiki": {"s3_prefix": "w2", "vfs_mount": "/wiki/p2/"},
            }
        ),
    ]

    out = await invoke_scoped_retrieval(
        "search",
        {"query": "hello", "collection": "ignored"},
        bindings=bindings,
        call_mcp=fake_call,
    )
    assert out["project_count"] == 2
    assert len(out["results"]) == 2
    assert {c["project_id"] for c in calls} == {"p1", "p2"}
