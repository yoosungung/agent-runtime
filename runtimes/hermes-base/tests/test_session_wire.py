"""Hermes SessionDB Postgres wiring — wire-dev integration (TDD).

Upstream hermes-agent SessionDB is still SQLite-first; pool-side contract is:
  - `HERMES_SESSION_DSN` env → `config.yaml` `sessions.state_backend=postgres`
  - DSN must be reachable from the pool process (same Postgres as wire-dev)

Run:
  uv run pytest runtimes/hermes-base/tests/test_session_wire.py -m integration -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hermes_base.profile_materializer import ProfileMaterializer
from hermes_base.settings import Settings
from hermes_base.vfs_profile import ProfileVfsSync

pytestmark = pytest.mark.integration


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "Session wire assistant.",
            "model": "openai/gpt-4o",
            "mcp_servers": ["search-server"],
            "skills": [],
            "max_iterations": 5,
        }
    }


@pytest.mark.asyncio()
async def test_wire_session_dsn_connects(wire_session_dsn: str) -> None:
    import asyncpg

    try:
        conn = await asyncpg.connect(wire_session_dsn)
    except OSError as exc:
        pytest.skip(f"wire-dev session Postgres unreachable: {exc}")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"wire-dev session Postgres connect failed: {exc}")
    try:
        assert await conn.fetchval("SELECT 1") == 1
    finally:
        await conn.close()


@pytest.mark.asyncio()
async def test_wire_materializer_writes_postgres_session_config(
    wire_session_dsn: str,
    tmp_path: Path,
) -> None:
    materializer = ProfileMaterializer(tmp_path)
    home = materializer.ensure("sess-bot", _sample_cfg(), session_dsn=wire_session_dsn)
    cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sessions"]["state_backend"] == "postgres"
    assert cfg["sessions"]["postgres_dsn"] == wire_session_dsn


@pytest.mark.asyncio()
async def test_wire_vfs_seed_persists_session_config(
    vfs_store,
    wire_session_dsn: str,
    wire_agent_name: str,
    cleanup_wire_agent,
    tmp_path: Path,
) -> None:
    sync = ProfileVfsSync(vfs_store)
    await sync.seed_from_config(wire_agent_name, _sample_cfg(), session_dsn=wire_session_dsn)
    scratch = tmp_path / "pull"
    await sync.pull(wire_agent_name, scratch)
    cfg = yaml.safe_load((scratch / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sessions"]["state_backend"] == "postgres"
    assert cfg["sessions"]["postgres_dsn"] == wire_session_dsn


def test_wire_settings_reads_hermes_session_dsn(
    wire_dev_env: dict[str, str],
    wire_session_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_SESSION_DSN", wire_session_dsn)
    settings = Settings()
    assert settings.hermes_session_dsn.replace("postgresql+asyncpg://", "postgresql://") == (
        wire_session_dsn
    )
