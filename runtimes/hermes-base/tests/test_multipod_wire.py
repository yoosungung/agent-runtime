"""Multi-pod wire-dev E2E — VFS memory + session DSN continuity without LLM invoke."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hermes_base.vfs_profile import ProfileVfsSync

pytestmark = pytest.mark.integration


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "Multi-pod wire assistant.",
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
async def test_wire_multipod_memory_and_session_dsn(
    sync: ProfileVfsSync,
    wire_agent_name: str,
    wire_session_dsn: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    """Pod A writes memory to VFS; Pod B pulls the same profile + session DSN."""
    await sync.seed_from_config(
        wire_agent_name, _sample_cfg(), session_dsn=wire_session_dsn
    )

    pod_a = tmp_path / "pod-a"
    manifest_a = await sync.pull(wire_agent_name, pod_a)
    (pod_a / "memories").mkdir(exist_ok=True)
    (pod_a / "memories" / "MEMORY.md").write_text(
        "# fact from pod A\n", encoding="utf-8"
    )
    await sync.push(wire_agent_name, pod_a, manifest_a)

    pod_b = tmp_path / "pod-b"
    await sync.pull(wire_agent_name, pod_b)

    memory = (pod_b / "memories" / "MEMORY.md").read_text(encoding="utf-8")
    assert "fact from pod A" in memory

    cfg = yaml.safe_load((pod_b / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sessions"]["state_backend"] == "postgres"
    assert cfg["sessions"]["postgres_dsn"] == wire_session_dsn
    assert (pod_b / "SOUL.md").read_text(encoding="utf-8").startswith("Multi-pod wire")


@pytest.mark.asyncio()
async def test_wire_multipod_soul_patch_visible_on_second_pod(
    sync: ProfileVfsSync,
    wire_agent_name: str,
    wire_session_dsn: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    """Backend-style config patch re-seeds VFS; Pod B sees updated soul."""
    await sync.seed_from_config(
        wire_agent_name, _sample_cfg(), session_dsn=wire_session_dsn
    )

    patched = _sample_cfg()
    patched["hermes"]["soul"] = "Patched soul for pod B."
    await sync.seed_from_config(
        wire_agent_name, patched, session_dsn=wire_session_dsn
    )

    pod_b = tmp_path / "pod-b"
    await sync.pull(wire_agent_name, pod_b)
    assert "Patched soul for pod B." in (pod_b / "SOUL.md").read_text(encoding="utf-8")
