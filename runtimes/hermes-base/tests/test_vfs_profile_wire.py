"""ProfileVfsSync integration tests — real Postgres VFS via wire-dev.

Prerequisites (agents-runtime repo root):
  ./scripts/wire-dev.sh up
  ./scripts/wire-dev.sh env

Run:
  uv run pytest runtimes/hermes-base/tests/test_vfs_profile_wire.py -m integration -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hermes_base.vfs_profile import ProfileVfsSync, vfs_path

pytestmark = pytest.mark.integration

KIND = "agent"


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "You are a wire-dev integration assistant.",
            "model": "openai/gpt-4o",
            "mcp_servers": ["search-server"],
            "skills": ["plan"],
            "max_iterations": 30,
        }
    }


@pytest.fixture()
def sync(vfs_store) -> ProfileVfsSync:
    return ProfileVfsSync(vfs_store)


@pytest.mark.asyncio()
async def test_wire_seed_and_pull(
    sync: ProfileVfsSync,
    vfs_store,
    wire_agent_name: str,
    wire_session_dsn: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    await sync.seed_from_config(wire_agent_name, _sample_cfg(), session_dsn=wire_session_dsn)
    scratch = tmp_path / "pull"
    manifest = await sync.pull(wire_agent_name, scratch)

    assert (scratch / "SOUL.md").read_text(encoding="utf-8").startswith("You are a wire-dev")
    cfg = yaml.safe_load((scratch / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sessions"]["state_backend"] == "postgres"
    assert cfg["sessions"]["postgres_dsn"] == wire_session_dsn
    assert (scratch / "skills" / "plan.enabled").is_file()
    assert len(manifest.files) >= 4

    record = await vfs_store.read(KIND, wire_agent_name, vfs_path("SOUL.md"))
    assert record is not None
    assert "wire-dev integration" in record.content


@pytest.mark.asyncio()
async def test_wire_push_writes_memory_changes(
    sync: ProfileVfsSync,
    vfs_store,
    wire_agent_name: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    await sync.seed_from_config(wire_agent_name, _sample_cfg())
    scratch = tmp_path / "work"
    manifest = await sync.pull(wire_agent_name, scratch)

    mem_dir = scratch / "memories"
    mem_dir.mkdir(exist_ok=True)
    mem_file = mem_dir / "MEMORY.md"
    mem_file.write_text("# learned from wire-dev\n", encoding="utf-8")

    stats = await sync.push(wire_agent_name, scratch, manifest)
    assert stats.written >= 1

    record = await vfs_store.read(KIND, wire_agent_name, vfs_path("memories/MEMORY.md"))
    assert record is not None
    assert "learned from wire-dev" in record.content

    scratch_b = tmp_path / "work-b"
    await sync.pull(wire_agent_name, scratch_b)
    assert "learned from wire-dev" in (scratch_b / "memories" / "MEMORY.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio()
async def test_wire_push_skips_unchanged(
    sync: ProfileVfsSync,
    wire_agent_name: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    await sync.seed_from_config(wire_agent_name, _sample_cfg())
    scratch = tmp_path / "work"
    manifest = await sync.pull(wire_agent_name, scratch)
    stats = await sync.push(wire_agent_name, scratch, manifest)
    assert stats.written == 0
    assert stats.skipped >= 1
