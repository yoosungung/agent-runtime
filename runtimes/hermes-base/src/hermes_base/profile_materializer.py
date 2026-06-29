"""Write Hermes profile files into invoke scratch (HERMES_HOME). VFS 정본은 ProfileVfsSync."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from hermes_base.schemas import parse_hermes_cfg

logger = logging.getLogger(__name__)


def profile_home(work_root: Path, agent_name: str) -> Path:
    """Invoke scratch: {HERMES_WORK_DIR}/{agent_name}/ == HERMES_HOME."""
    return work_root / agent_name


def config_fingerprint(cfg: dict) -> str:
    payload = json.dumps(cfg.get("hermes") or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def config_needs_reconcile(scratch: Path, cfg: dict) -> bool:
    """True when registration config fingerprint differs from scratch meta."""
    meta_path = scratch / ".runtime-meta.json"
    if not meta_path.is_file():
        return True
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
        return existing.get("fingerprint") != config_fingerprint(cfg)
    except (json.JSONDecodeError, OSError):
        return True


def build_config_yaml(cfg: dict, *, session_dsn: str | None = None) -> str:
    hermes = parse_hermes_cfg(cfg)
    hermes_yaml: dict[str, Any] = {
        "agent": {"max_turns": hermes.max_iterations},
        "sessions": {"state_backend": "postgres" if session_dsn else "sqlite"},
    }
    if session_dsn:
        hermes_yaml["sessions"]["postgres_dsn"] = session_dsn
    if hermes.model:
        hermes_yaml.setdefault("model", {})["default"] = hermes.model
    return yaml.safe_dump(hermes_yaml, sort_keys=False, allow_unicode=True)


class ProfileMaterializer:
    """Write SOUL.md, config.yaml, skills markers into scratch after VFS pull."""

    def __init__(self, work_root: Path) -> None:
        self._root = work_root

    def home_for(self, agent_name: str) -> Path:
        return profile_home(self._root, agent_name)

    def ensure(
        self,
        agent_name: str,
        cfg: dict,
        *,
        session_dsn: str | None = None,
        force: bool = False,
    ) -> Path:
        hermes = parse_hermes_cfg(cfg)
        home = self.home_for(agent_name)
        meta_path = home / ".runtime-meta.json"
        fp = config_fingerprint(cfg)

        if not force and meta_path.is_file():
            try:
                existing = json.loads(meta_path.read_text(encoding="utf-8"))
                if existing.get("fingerprint") == fp:
                    return home
            except (json.JSONDecodeError, OSError):
                pass

        home.mkdir(parents=True, exist_ok=True)
        (home / "SOUL.md").write_text(hermes.soul.strip() + "\n", encoding="utf-8")
        (home / "config.yaml").write_text(
            build_config_yaml(cfg, session_dsn=session_dsn),
            encoding="utf-8",
        )

        skills_dir = home / "skills"
        skills_dir.mkdir(exist_ok=True)
        for skill_name in hermes.skills:
            marker = skills_dir / f"{skill_name}.enabled"
            marker.write_text("", encoding="utf-8")

        meta_path.write_text(
            json.dumps({"fingerprint": fp, "agent": agent_name}, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("profile_materialized", extra={"agent": agent_name, "home": str(home)})
        return home
