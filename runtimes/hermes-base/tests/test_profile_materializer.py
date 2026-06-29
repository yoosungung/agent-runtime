"""Profile materializer tests — TDD."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hermes_base.profile_materializer import ProfileMaterializer, config_fingerprint


@pytest.fixture()
def materializer(tmp_path: Path) -> ProfileMaterializer:
    return ProfileMaterializer(tmp_path)


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "You are a helpful research assistant.",
            "model": "anthropic/claude-sonnet-4-6",
            "mcp_servers": ["search-server"],
            "mcp_tools": [{"server": "search-server", "name": "naver_search", "description": "search"}],
            "enabled_toolsets": ["web", "runtime_mcp"],
            "skills": ["plan"],
            "max_iterations": 45,
        }
    }


def test_materialize_writes_soul_and_config(materializer: ProfileMaterializer) -> None:
    home = materializer.ensure("my-special-hermes", _sample_cfg(), session_dsn="postgresql://u:p@db/hermes")
    assert home.is_dir()
    assert (home / "SOUL.md").read_text(encoding="utf-8").startswith("You are a helpful")
    cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["sessions"]["state_backend"] == "postgres"
    assert cfg["sessions"]["postgres_dsn"] == "postgresql://u:p@db/hermes"
    assert cfg["agent"]["max_turns"] == 45
    assert (home / "skills" / "plan.enabled").is_file()


def test_materialize_idempotent_skip(materializer: ProfileMaterializer) -> None:
    cfg = _sample_cfg()
    home1 = materializer.ensure("bot-a", cfg)
    mtime_soul = (home1 / "SOUL.md").stat().st_mtime
    home2 = materializer.ensure("bot-a", cfg)
    assert home1 == home2
    assert (home2 / "SOUL.md").stat().st_mtime == mtime_soul


def test_materialize_rewrites_on_config_change(materializer: ProfileMaterializer) -> None:
    cfg = _sample_cfg()
    materializer.ensure("bot-b", cfg)
    cfg2 = _sample_cfg()
    cfg2["hermes"]["soul"] = "Updated persona."
    materializer.ensure("bot-b", cfg2)
    assert "Updated persona" in (materializer.home_for("bot-b") / "SOUL.md").read_text(encoding="utf-8")


def test_config_fingerprint_stable() -> None:
    cfg = _sample_cfg()
    assert config_fingerprint(cfg) == config_fingerprint(cfg)
    cfg2 = _sample_cfg()
    cfg2["hermes"]["soul"] = "x"
    assert config_fingerprint(cfg) != config_fingerprint(cfg2)


def test_parse_requires_soul_and_mcp(tmp_path: Path) -> None:
    materializer = ProfileMaterializer(tmp_path)
    with pytest.raises(ValueError, match="soul"):
        materializer.ensure("x", {"hermes": {"mcp_servers": ["a"]}})
