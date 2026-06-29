"""Sync Hermes profile tree between agents-runtime VFS and local scratch (HERMES_HOME)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hermes_base.profile_materializer import build_config_yaml, config_fingerprint
from hermes_base.schemas import parse_hermes_cfg
from runtime_common.vfs.store import AgentVfsStore

logger = logging.getLogger(__name__)

PROFILE_PREFIX = "/profile"
KIND = "agent"


@dataclass
class PullManifest:
    """VFS paths pulled into scratch — push uses file mtime vs this snapshot."""

    files: dict[str, datetime] = field(default_factory=dict)


@dataclass
class PushStats:
    written: int = 0
    skipped: int = 0


def vfs_path(relative: str) -> str:
    rel = relative.lstrip("/")
    return f"{PROFILE_PREFIX}/{rel}" if rel else PROFILE_PREFIX


def scratch_file(dest: Path, vfs_full_path: str) -> Path:
    assert vfs_full_path.startswith(PROFILE_PREFIX)
    suffix = vfs_full_path[len(PROFILE_PREFIX) :].lstrip("/")
    return dest / suffix if suffix else dest


class ProfileVfsSync:
    """Pull profile tree from VFS to scratch; push runtime mutations back."""

    def __init__(self, store: AgentVfsStore, *, prefix: str = PROFILE_PREFIX) -> None:
        self._store = store
        self._prefix = prefix.rstrip("/") or PROFILE_PREFIX

    async def pull(self, agent_name: str, dest: Path) -> PullManifest:
        dest.mkdir(parents=True, exist_ok=True)
        pattern = f"{self._prefix}/**"
        paths = await self._store.glob(KIND, agent_name, pattern)
        manifest = PullManifest()
        for vp in sorted(paths):
            record = await self._store.read(KIND, agent_name, vp)
            if record is None:
                continue
            out = scratch_file(dest, vp)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(record.content, encoding="utf-8")
            manifest.files[vp] = datetime.fromtimestamp(out.stat().st_mtime, tz=UTC)
        logger.info("vfs_pull", extra={"agent": agent_name, "files": len(manifest.files)})
        return manifest

    async def push(self, agent_name: str, src: Path, manifest: PullManifest) -> PushStats:
        stats = PushStats()
        if not src.is_dir():
            return stats
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            vp = vfs_path(rel)
            content = path.read_text(encoding="utf-8")
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            prev = manifest.files.get(vp)
            if prev is not None and mtime <= prev:
                stats.skipped += 1
                continue
            await self._store.write(KIND, agent_name, vp, content, overwrite=True)
            stats.written += 1
        logger.info(
            "vfs_push",
            extra={"agent": agent_name, "written": stats.written, "skipped": stats.skipped},
        )
        return stats

    async def seed_from_config(
        self,
        agent_name: str,
        cfg: dict,
        *,
        session_dsn: str | None = None,
    ) -> None:
        """Seed VFS from registration config (backend + pool reconcile)."""
        hermes = parse_hermes_cfg(cfg)
        fp = config_fingerprint(cfg)
        await self._store.write(
            KIND, agent_name, vfs_path("SOUL.md"), hermes.soul.strip() + "\n", overwrite=True
        )
        await self._store.write(
            KIND,
            agent_name,
            vfs_path("config.yaml"),
            build_config_yaml(cfg, session_dsn=session_dsn),
            overwrite=True,
        )
        for skill_name in hermes.skills:
            await self._store.write(
                KIND,
                agent_name,
                vfs_path(f"skills/{skill_name}.enabled"),
                "",
                overwrite=True,
            )
        await self._store.write(
            KIND,
            agent_name,
            vfs_path(".runtime-meta.json"),
            json.dumps({"fingerprint": fp, "agent": agent_name}, indent=2) + "\n",
            overwrite=True,
        )
