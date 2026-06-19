"""Tests for runtime_common.vfs — scope isolation and CRUD."""

from __future__ import annotations

import pytest

from runtime_common.vfs.composite import build_general_vfs
from runtime_common.vfs.database_backend import AgentDatabaseBackend, UserDatabaseBackend
from runtime_common.vfs.store import MemoryAgentVfsStore, MemoryUserVfsStore


@pytest.fixture
def agent_store():
    return MemoryAgentVfsStore()


@pytest.fixture
def user_store():
    return MemoryUserVfsStore()


@pytest.mark.asyncio
async def test_agent_scope_shared_across_users(agent_store):
    backend_a = AgentDatabaseBackend(agent_store, "agent", "research-bot")
    backend_b = AgentDatabaseBackend(agent_store, "agent", "research-bot")

    assert (await backend_a.awrite("/notes.md", "shared knowledge")).error is None
    result = await backend_b.aread("/notes.md")
    assert result.error is None
    assert "shared knowledge" in result.file_data["content"]


@pytest.mark.asyncio
async def test_agent_scope_isolated_by_name(agent_store):
    a = AgentDatabaseBackend(agent_store, "agent", "bot-a")
    b = AgentDatabaseBackend(agent_store, "agent", "bot-b")

    await a.awrite("/data.txt", "a-only")
    read_b = await b.aread("/data.txt")
    assert read_b.error is not None


@pytest.mark.asyncio
async def test_agent_scope_shared_across_versions_same_name(agent_store):
    """Same (kind, name) key — version is not part of VFS scope."""
    v1_backend = AgentDatabaseBackend(agent_store, "agent", "research-bot")
    v2_backend = AgentDatabaseBackend(agent_store, "agent", "research-bot")

    await v1_backend.awrite("/kb.md", "from v1")
    result = await v2_backend.aread("/kb.md")
    assert result.error is None
    assert "from v1" in result.file_data["content"]


@pytest.mark.asyncio
async def test_user_scope_cross_agent(user_store):
    backend = UserDatabaseBackend(user_store, user_id=42)
    await backend.awrite("/profile.md", "my notes")

    same_user = UserDatabaseBackend(user_store, user_id=42)
    result = await same_user.aread("/profile.md")
    assert result.error is None

    other_user = UserDatabaseBackend(user_store, user_id=99)
    assert (await other_user.aread("/profile.md")).error is not None


@pytest.mark.asyncio
async def test_write_rejects_existing_file(agent_store):
    backend = AgentDatabaseBackend(agent_store, "agent", "x")
    await backend.awrite("/f.txt", "one")
    result = await backend.awrite("/f.txt", "two")
    assert result.error is not None
    read_result = await backend.aread("/f.txt")
    assert "one" in read_result.file_data["content"]


@pytest.mark.asyncio
async def test_edit_replaces_content(agent_store):
    backend = AgentDatabaseBackend(agent_store, "agent", "x")
    await backend.awrite("/f.txt", "hello world")
    edit = await backend.aedit("/f.txt", "world", "there")
    assert edit.error is None
    assert edit.occurrences == 1
    read_result = await backend.aread("/f.txt")
    assert "hello there" in read_result.file_data["content"]


@pytest.mark.asyncio
async def test_ls_lists_direct_children(agent_store):
    backend = AgentDatabaseBackend(agent_store, "agent", "x")
    await backend.awrite("/dir/a.txt", "a")
    await backend.awrite("/dir/b.txt", "b")
    await backend.awrite("/top.txt", "t")

    ls_root = await backend.als("/")
    paths = {e["path"] for e in ls_root.entries or []}
    assert "/top.txt" in paths
    assert "/dir/" in paths

    ls_dir = await backend.als("/dir/")
    dir_paths = {e["path"] for e in ls_dir.entries or []}
    assert "/dir/a.txt" in dir_paths
    assert "/dir/b.txt" in dir_paths


@pytest.mark.asyncio
async def test_glob_and_grep(agent_store):
    backend = AgentDatabaseBackend(agent_store, "agent", "x")
    await backend.awrite("/src/a.py", "def foo(): pass")
    await backend.awrite("/src/b.txt", "no match")

    glob = await backend.aglob("**/*.py")
    assert "/src/a.py" in (glob.matches or [])

    grep = await backend.agrep("def foo")
    assert len(grep.matches or []) == 1


@pytest.mark.asyncio
async def test_composite_routes_agent_and_user_prefixes(agent_store, user_store):
    vfs = build_general_vfs(
        agent_store,
        user_store,
        kind="agent",
        agent_name="bot",
        user_id=7,
    )
    assert (await vfs.awrite("/agent/shared.md", "team")).error is None
    assert (await vfs.awrite("/user/private.md", "mine")).error is None

    agent_read = await vfs.aread("/agent/shared.md")
    user_read = await vfs.aread("/user/private.md")
    assert "team" in agent_read.file_data["content"]
    assert "mine" in user_read.file_data["content"]

    # User 7 data not visible to another user backend on /user/
    other = UserDatabaseBackend(user_store, user_id=8)
    assert (await other.aread("/private.md")).error is not None
