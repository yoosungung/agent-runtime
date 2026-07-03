"""Tests for knowledge helpers."""

from __future__ import annotations

import pytest

from runtime_common.knowledge.models import KnowledgeBinding
from runtime_common.knowledge.policy import mcp_requires_knowledge_project
from runtime_common.knowledge.resolve import resolve_knowledge_bindings
from runtime_common.knowledge.rrf import reciprocal_rank_fusion
from runtime_common.knowledge.scope import invoke_scoped_retrieval, scope_search_arguments
from runtime_common.vfs.composite import wiki_routes_from_bindings


def test_mcp_requires_knowledge_project():
    assert mcp_requires_knowledge_project({}) is False
    assert mcp_requires_knowledge_project({"knowledge": {"requires_project": True}}) is True


def test_scope_search_arguments_overwrites_index_namespace():
    binding = KnowledgeBinding.from_api_dict(
        {
            "tenant": "acme",
            "project_id": "p1",
            "project_slug": "default",
            "rag": {"index_namespace": "path_graph_acme_default", "filter": {"project_id": "p1"}},
            "graph": {"nebula_space": "space-a"},
            "wiki": {"s3_prefix": "wiki/a", "vfs_mount": "/wiki/a/"},
        }
    )
    scoped = scope_search_arguments({"query": "x", "index_namespace": "evil"}, binding)
    assert scoped["index_namespace"] == "path_graph_acme_default"
    assert scoped["project_id"] == "p1"
    assert scoped["tenant"] == "acme"
    assert scoped["project_slug"] == "default"
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
                "rag": {"index_namespace": "path_graph_t_p1", "filter": {}},
                "graph": {"nebula_space": "g1"},
                "wiki": {"s3_prefix": "w1", "vfs_mount": "/wiki/p1/"},
            }
        ),
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "t",
                "project_id": "p2",
                "rag": {"index_namespace": "path_graph_t_p2", "filter": {}},
                "graph": {"nebula_space": "g2"},
                "wiki": {"s3_prefix": "w2", "vfs_mount": "/wiki/p2/"},
            }
        ),
    ]

    out = await invoke_scoped_retrieval(
        "search",
        {"query": "hello", "index_namespace": "ignored"},
        bindings=bindings,
        call_mcp=fake_call,
    )
    assert out["project_count"] == 2
    assert len(out["results"]) == 2
    assert {c["project_id"] for c in calls} == {"p1", "p2"}


def test_resolve_knowledge_bindings_uses_fetcher():
    seen: list[tuple[str, str]] = []

    def fetch(tenant: str, project_id: str) -> dict:
        seen.append((tenant, project_id))
        return {
            "tenant": tenant,
            "project_id": project_id,
            "rag": {"index_namespace": f"path_graph_{tenant}_{project_id}", "filter": {}},
            "graph": {"nebula_space": f"g-{project_id}"},
            "wiki": {"s3_prefix": f"w/{project_id}", "vfs_mount": f"/wiki/{project_id}/"},
        }

    bindings = resolve_knowledge_bindings("acme", ["p1", "p2"], fetch_binding=fetch)
    assert len(bindings) == 2
    assert seen == [("acme", "p1"), ("acme", "p2")]
    assert bindings[0].rag.index_namespace == "path_graph_acme_p1"


def test_resolve_knowledge_bindings_rejects_tenant_mismatch():
    def fetch(_tenant: str, project_id: str) -> dict:
        return {
            "tenant": "other",
            "project_id": project_id,
            "rag": {"index_namespace": "path_graph_other_x", "filter": {}},
            "graph": {"nebula_space": "g"},
            "wiki": {"s3_prefix": "w", "vfs_mount": "/wiki/"},
        }

    with pytest.raises(ValueError, match="tenant mismatch"):
        resolve_knowledge_bindings("acme", ["p1"], fetch_binding=fetch)


def test_wiki_routes_from_bindings_distinct_mounts():
    bindings = [
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "t",
                "project_id": "p1",
                "rag": {"index_namespace": "path_graph_t_a", "filter": {}},
                "graph": {"nebula_space": "g1"},
                "wiki": {"s3_prefix": "wiki/p1/", "vfs_mount": "/wiki/a/"},
            }
        ),
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "t",
                "project_id": "p2",
                "rag": {"index_namespace": "path_graph_t_b", "filter": {}},
                "graph": {"nebula_space": "g2"},
                "wiki": {"s3_prefix": "wiki/p2/", "vfs_mount": "/wiki/b/"},
            }
        ),
    ]
    routes = wiki_routes_from_bindings(bindings, s3_client=object(), bucket="wiki-bucket")
    assert set(routes) == {"/wiki/a/", "/wiki/b/"}
