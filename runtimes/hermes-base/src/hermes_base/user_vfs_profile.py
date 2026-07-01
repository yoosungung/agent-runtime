"""Per-user USER.md sync between UserVfsStore and invoke scratch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from hermes_base.vfs_errors import ProfileVfsConflictError
from hermes_base.vfs_profile import PullFileState, PullManifest, PushStats
from runtime_common.vfs.store import UserVfsStore

logger = logging.getLogger(__name__)

USER_VFS_PREFIX = "/hermes"
USER_SCOPED_SCRATCH_REL = "memories/USER.md"


def user_vfs_path(agent_name: str, scratch_rel: str) -> str:
    rel = scratch_rel.lstrip("/")
    return f"{USER_VFS_PREFIX}/{agent_name}/{rel}" if rel else f"{USER_VFS_PREFIX}/{agent_name}"


def user_scratch_file(dest: Path) -> Path:
    return dest / USER_SCOPED_SCRATCH_REL


class UserProfileVfsSync:
    """Overlay pull and push for per-user USER.md only."""

    def __init__(self, store: UserVfsStore, *, prefix: str = USER_VFS_PREFIX) -> None:
        self._store = store
        self._prefix = prefix.rstrip("/") or USER_VFS_PREFIX

    @staticmethod
    def empty_manifest() -> PullManifest:
        return PullManifest()

    async def pull_overlay(self, user_id: int, agent_name: str, dest: Path) -> PullManifest:
        vp = user_vfs_path(agent_name, USER_SCOPED_SCRATCH_REL)
        record = await self._store.read(user_id, vp)
        manifest = PullManifest()
        if record is None:
            return manifest

        out = user_scratch_file(dest)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(record.content, encoding="utf-8")
        scratch_mtime = datetime.fromtimestamp(out.stat().st_mtime, tz=UTC)
        manifest.files[vp] = PullFileState(
            scratch_mtime=scratch_mtime,
            vfs_modified_at=record.modified_at,
        )
        logger.info(
            "user_vfs_pull_overlay",
            extra={"user_id": user_id, "agent": agent_name, "path": vp},
        )
        return manifest

    async def push(
        self,
        user_id: int,
        agent_name: str,
        src: Path,
        manifest: PullManifest,
    ) -> PushStats:
        stats = PushStats()
        path = user_scratch_file(src)
        if not path.is_file():
            return stats

        vp = user_vfs_path(agent_name, USER_SCOPED_SCRATCH_REL)
        content = path.read_text(encoding="utf-8")
        local_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        state = manifest.files.get(vp)
        if state is not None and local_mtime <= state.scratch_mtime:
            stats.skipped += 1
            return stats

        if state is not None and state.vfs_modified_at is not None:
            current = await self._store.read(user_id, vp)
            cur_at = current.modified_at if current else None
            if cur_at != state.vfs_modified_at:
                logger.warning(
                    "user_vfs_push_conflict",
                    extra={"user_id": user_id, "agent": agent_name, "path": vp},
                )
                raise ProfileVfsConflictError(agent_name, [vp])

        await self._store.write(user_id, vp, content, overwrite=True)
        stats.written += 1
        logger.info(
            "user_vfs_push",
            extra={"user_id": user_id, "agent": agent_name, "written": stats.written},
        )
        return stats
