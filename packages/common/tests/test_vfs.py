"""Tests for runtime_common.vfs — scope isolation and CRUD."""

from __future__ import annotations

import re

import pytest

from runtime_common.vfs.composite import build_general_vfs
from runtime_common.vfs.database_backend import AgentDatabaseBackend, UserDatabaseBackend
from runtime_common.vfs.paths import (
    glob_to_pg_regex,
    plan_glob_sql,
    vfs_entry_metadata,
)
from runtime_common.vfs.store import (
    MemoryAgentVfsStore,
    MemoryUserVfsStore,
    asyncpg_pool_kwargs,
)


def test_asyncpg_pool_kwargs_strips_sslmode_disable():
    dsn, kwargs = asyncpg_pool_kwargs(
        "postgresql://u:p@postgres:5432/db?sslmode=disable&connect_timeout=10"
    )
    assert dsn == "postgresql://u:p@postgres:5432/db?connect_timeout=10"
    assert kwargs == {"ssl": False}


def test_asyncpg_pool_kwargs_pgbouncer_disables_statement_cache():
    dsn, kwargs = asyncpg_pool_kwargs(
        "postgresql://u:p@pgbouncer-rw:5432/db",
        pgbouncer=True,
    )
    assert dsn == "postgresql://u:p@pgbouncer-rw:5432/db"
    assert kwargs == {"statement_cache_size": 0}


def test_vfs_entry_metadata_root_level_file():
    parent_path, name, size = vfs_entry_metadata("/notes.md", b"hello")
    assert parent_path == "/"
    assert name == "notes.md"
    assert size == 5


def test_vfs_entry_metadata_nested_file():
    parent_path, name, size = vfs_entry_metadata("/dir/a.txt", b"abc")
    assert parent_path == "/dir/"
    assert name == "a.txt"
    assert size == 3


def test_glob_to_pg_regex():
    assert re.match(glob_to_pg_regex("**/*.py"), "/src/a.py")
    assert re.match(glob_to_pg_regex("**/*.py"), "/a.py")
    assert not re.match(glob_to_pg_regex("**/*.py"), "/src/a.txt")


def test_plan_glob_sql_exact_path():
    plan = plan_glob_sql("/notes.md")
    assert plan.path_exact == "/notes.md"
    assert not plan.use_regex


def test_plan_glob_sql_suffix_glob():
    plan = plan_glob_sql("**/*.py")
    assert plan.name_like == "%.py"
    assert plan.path_prefix is None
    assert not plan.use_regex


def test_plan_glob_sql_prefixed_suffix_glob():
    plan = plan_glob_sql("/src/**/*.py")
    assert plan.path_prefix == "/src/"
    assert plan.name_like == "%.py"
    assert not plan.use_regex


def test_plan_glob_sql_recursive_dir():
    plan = plan_glob_sql("/src/**")
    assert plan.path_prefix == "/src/"
    assert plan.name_like is None
    assert not plan.use_regex


def test_plan_glob_sql_single_segment_wildcard_uses_regex():
    plan = plan_glob_sql("/src/*")
    assert plan.path_prefix == "/src/"
    assert plan.use_regex


def test_plan_glob_sql_midpath_wildcard_uses_regex():
    plan = plan_glob_sql("/fo*/bar.txt")
    assert plan.use_regex


def test_plan_glob_sql_match_all_uses_regex():
    plan = plan_glob_sql("/**")
    assert plan.use_regex


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
async def test_write_materializes_parent_dirs(agent_store):
    store = agent_store
    await store.write("agent", "x", "/deep/nested/file.txt", "data")
    entries = await store.list_dir("agent", "x", "/deep/")
    paths = {e.path for e in entries}
    assert "/deep/nested/" in paths

    nested = await store.list_dir("agent", "x", "/deep/nested/")
    nested_paths = {e.path for e in nested}
    assert "/deep/nested/file.txt" in nested_paths


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
async def test_user_mkdir_and_delete_tree(user_store):
    await user_store.mkdir(42, "/docs/")
    await user_store.write(42, "/docs/readme.md", "hello")
    entries = await user_store.list_dir(42, "/")
    names = {e.name for e in entries}
    assert "docs" in names

    await user_store.delete_tree(42, "/docs/")
    entries = await user_store.list_dir(42, "/")
    assert entries == []


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
