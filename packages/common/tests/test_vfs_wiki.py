"""Tests for wiki VFS store and read-only backend."""

from __future__ import annotations

import pytest

from runtime_common.knowledge.models import KnowledgeBinding
from runtime_common.vfs.composite import wiki_routes_from_bindings
from runtime_common.vfs.database_backend import WikiDatabaseBackend
from runtime_common.vfs.wiki_store import MemoryWikiVfsStore


@pytest.fixture
def wiki_store() -> MemoryWikiVfsStore:
    return MemoryWikiVfsStore()


@pytest.mark.asyncio
async def test_wiki_store_write_read(wiki_store: MemoryWikiVfsStore):
    await wiki_store.write("acme", "p1", "/page.md", "# Hello", overwrite=True)
    record = await wiki_store.read("acme", "p1", "/page.md")
    assert record is not None
    assert record.content == "# Hello"


@pytest.mark.asyncio
async def test_wiki_database_backend_read_only(wiki_store: MemoryWikiVfsStore):
    await wiki_store.write("acme", "p1", "/page.md", "content", overwrite=True)
    backend = WikiDatabaseBackend(wiki_store, "acme", "p1", read_only=True)
    result = await backend.aread("/page.md")
    assert result.error is None
    payload = result.file_data
    text = payload.content if hasattr(payload, "content") else payload.get("content", "")
    assert "content" in text
    write_result = await backend.awrite("/new.md", "x")
    assert write_result.error == "wiki mount is read-only"


def test_wiki_routes_from_bindings_pg(wiki_store: MemoryWikiVfsStore):
    bindings = [
        KnowledgeBinding.from_api_dict(
            {
                "tenant": "acme",
                "project_id": "p1",
                "project_slug": "docs",
                "rag": {"index_namespace": "ns", "filter": {}},
                "graph": {"nebula_space": "ns"},
                "wiki": {"vfs_mount": "/wiki/docs/"},
            }
        ),
    ]
    routes = wiki_routes_from_bindings(bindings, wiki_store=wiki_store, read_only=True)
    assert set(routes) == {"/wiki/docs/"}
    assert isinstance(routes["/wiki/docs/"], WikiDatabaseBackend)
