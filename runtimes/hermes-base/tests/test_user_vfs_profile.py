"""UserProfileVfsSync tests — per-user USER.md overlay (TDD)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_base.user_vfs_profile import (
    USER_SCOPED_SCRATCH_REL,
    UserProfileVfsSync,
    user_vfs_path,
)
from hermes_base.vfs_profile import ProfileVfsSync, vfs_path
from runtime_common.vfs.store import MemoryAgentVfsStore, MemoryUserVfsStore

KIND = "agent"
AGENT = "my-special-hermes"
USER_ID = 42


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "You are helpful.",
            "model": "openai/gpt-4o",
            "mcp_servers": ["mcp-a"],
            "skills": [],
            "max_iterations": 10,
        }
    }


@pytest.fixture()
def agent_store() -> MemoryAgentVfsStore:
    return MemoryAgentVfsStore()


@pytest.fixture()
def user_store() -> MemoryUserVfsStore:
    return MemoryUserVfsStore()


@pytest.fixture()
def agent_sync(agent_store: MemoryAgentVfsStore) -> ProfileVfsSync:
    return ProfileVfsSync(agent_store)


@pytest.fixture()
def user_sync(user_store: MemoryUserVfsStore) -> UserProfileVfsSync:
    return UserProfileVfsSync(user_store)


@pytest.mark.asyncio()
async def test_user_vfs_path_convention() -> None:
    assert user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL) == (
        f"/hermes/{AGENT}/memories/USER.md"
    )


@pytest.mark.asyncio()
async def test_pull_overlay_writes_user_user_md(
    user_sync: UserProfileVfsSync,
    user_store: MemoryUserVfsStore,
    tmp_path: Path,
) -> None:
    vp = user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL)
    await user_store.write(USER_ID, vp, "# user prefs\n", overwrite=True)

    scratch = tmp_path / "work"
    scratch.mkdir()
    (scratch / "memories").mkdir()
    (scratch / "memories" / "USER.md").write_text("# agent default\n", encoding="utf-8")

    manifest = await user_sync.pull_overlay(USER_ID, AGENT, scratch)
    assert (scratch / "memories" / "USER.md").read_text(encoding="utf-8") == "# user prefs\n"
    assert vp in manifest.files


@pytest.mark.asyncio()
async def test_pull_overlay_noop_when_user_file_missing(
    user_sync: UserProfileVfsSync,
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "work"
    scratch.mkdir()
    (scratch / "memories").mkdir()
    (scratch / "memories" / "USER.md").write_text("# agent default\n", encoding="utf-8")

    manifest = await user_sync.pull_overlay(USER_ID, AGENT, scratch)
    assert manifest.files == {}
    assert (scratch / "memories" / "USER.md").read_text(encoding="utf-8") == "# agent default\n"


@pytest.mark.asyncio()
async def test_push_writes_user_user_md(
    user_sync: UserProfileVfsSync,
    user_store: MemoryUserVfsStore,
    tmp_path: Path,
) -> None:
    scratch = tmp_path / "work"
    scratch.mkdir()
    mem = scratch / "memories"
    mem.mkdir()
    (mem / "USER.md").write_text("# updated prefs\n", encoding="utf-8")

    stats = await user_sync.push(USER_ID, AGENT, scratch, user_sync.empty_manifest())
    assert stats.written == 1

    record = await user_store.read(USER_ID, user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL))
    assert record is not None
    assert "updated prefs" in record.content


@pytest.mark.asyncio()
async def test_agent_push_skips_user_md(
    agent_sync: ProfileVfsSync,
    agent_store: MemoryAgentVfsStore,
    tmp_path: Path,
) -> None:
    await agent_sync.seed_from_config(AGENT, _sample_cfg())
    scratch = tmp_path / "work"
    manifest = await agent_sync.pull(AGENT, scratch)

    mem = scratch / "memories"
    mem.mkdir(exist_ok=True)
    (mem / "USER.md").write_text("# should not land in agent vfs\n", encoding="utf-8")

    stats = await agent_sync.push(AGENT, scratch, manifest)
    assert stats.written == 0

    record = await agent_store.read(KIND, AGENT, vfs_path("memories/USER.md"))
    assert record is None or "should not land" not in (record.content or "")


@pytest.mark.asyncio()
async def test_users_isolated_per_user_id(
    user_sync: UserProfileVfsSync,
    user_store: MemoryUserVfsStore,
    tmp_path: Path,
) -> None:
    scratch_a = tmp_path / "a"
    scratch_b = tmp_path / "b"
    for s in (scratch_a, scratch_b):
        s.mkdir()
        (s / "memories").mkdir()
        (s / "memories" / "USER.md").write_text(f"# user {s.name}\n", encoding="utf-8")

    await user_sync.push(USER_ID, AGENT, scratch_a, user_sync.empty_manifest())
    await user_sync.push(99, AGENT, scratch_b, user_sync.empty_manifest())

    a = await user_store.read(USER_ID, user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL))
    b = await user_store.read(99, user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL))
    assert a is not None and "user a" in a.content
    assert b is not None and "user b" in b.content


@pytest.mark.asyncio()
async def test_push_detects_user_vfs_conflict(
    user_sync: UserProfileVfsSync,
    user_store: MemoryUserVfsStore,
    tmp_path: Path,
) -> None:
    from hermes_base.vfs_errors import ProfileVfsConflictError

    vp = user_vfs_path(AGENT, USER_SCOPED_SCRATCH_REL)
    await user_store.write(USER_ID, vp, "original\n", overwrite=True)

    scratch = tmp_path / "work"
    scratch.mkdir()
    (scratch / "memories").mkdir()
    manifest = await user_sync.pull_overlay(USER_ID, AGENT, scratch)

    await user_store.write(USER_ID, vp, "external change\n", overwrite=True)
    (scratch / "memories" / "USER.md").write_text("local edit\n", encoding="utf-8")

    with pytest.raises(ProfileVfsConflictError) as exc_info:
        await user_sync.push(USER_ID, AGENT, scratch, manifest)
    assert vp in exc_info.value.paths
