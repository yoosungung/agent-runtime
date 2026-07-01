"""ProfileVfsSync tests — MemoryAgentVfsStore (TDD)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_base.vfs_profile import ProfileVfsSync, vfs_path
from runtime_common.vfs.store import MemoryAgentVfsStore

KIND = "agent"
AGENT = "my-special-hermes"


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "You are a research assistant.",
            "model": "anthropic/claude-sonnet-4-6",
            "mcp_servers": ["search-server"],
            "skills": ["plan"],
            "max_iterations": 30,
        }
    }


@pytest.fixture()
def store() -> MemoryAgentVfsStore:
    return MemoryAgentVfsStore()


@pytest.fixture()
def sync(store: MemoryAgentVfsStore) -> ProfileVfsSync:
    return ProfileVfsSync(store)


@pytest.mark.asyncio()
async def test_seed_and_pull(sync: ProfileVfsSync, tmp_path: Path) -> None:
    await sync.seed_from_config(AGENT, _sample_cfg(), session_dsn="postgresql://localhost/db")
    scratch = tmp_path / "work"
    manifest = await sync.pull(AGENT, scratch)
    assert (scratch / "SOUL.md").read_text(encoding="utf-8").startswith("You are a research")
    assert (scratch / "config.yaml").read_text(encoding="utf-8")
    assert (scratch / "skills" / "plan.enabled").is_file()
    assert len(manifest.files) >= 4


@pytest.mark.asyncio()
async def test_seed_syncs_skill_markers_on_update(sync: ProfileVfsSync, tmp_path: Path) -> None:
    await sync.seed_from_config(AGENT, _sample_cfg())
    updated = _sample_cfg()
    updated["hermes"]["skills"] = ["search"]
    await sync.seed_from_config(AGENT, updated)

    plan = await sync._store.read(KIND, AGENT, vfs_path("skills/plan.enabled"))
    search = await sync._store.read(KIND, AGENT, vfs_path("skills/search.enabled"))
    assert plan is None
    assert search is not None

    scratch = tmp_path / "work"
    await sync.pull(AGENT, scratch)
    assert not (scratch / "skills" / "plan.enabled").exists()
    assert (scratch / "skills" / "search.enabled").is_file()


@pytest.mark.asyncio()
async def test_push_writes_memory_changes(sync: ProfileVfsSync, tmp_path: Path) -> None:
    await sync.seed_from_config(AGENT, _sample_cfg())
    scratch = tmp_path / "work"
    manifest = await sync.pull(AGENT, scratch)

    mem_dir = scratch / "memories"
    mem_dir.mkdir(exist_ok=True)
    (mem_dir / "MEMORY.md").write_text("# learned fact\n", encoding="utf-8")

    stats = await sync.push(AGENT, scratch, manifest)
    assert stats.written >= 1

    record = await sync._store.read(KIND, AGENT, vfs_path("memories/MEMORY.md"))
    assert record is not None
    assert "learned fact" in record.content


@pytest.mark.asyncio()
async def test_push_skips_unchanged(sync: ProfileVfsSync, tmp_path: Path) -> None:
    await sync.seed_from_config(AGENT, _sample_cfg())
    scratch = tmp_path / "work"
    manifest = await sync.pull(AGENT, scratch)
    stats = await sync.push(AGENT, scratch, manifest)
    assert stats.written == 0
    assert stats.skipped >= 1
