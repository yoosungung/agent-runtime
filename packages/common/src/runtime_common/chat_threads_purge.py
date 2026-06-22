"""Purge provider storage for soft-deleted chat threads."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from runtime_common.db.models import ChatThreadRow

logger = logging.getLogger(__name__)


async def _purge_langgraph(session: AsyncSession, provider_session_id: str) -> None:
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        await session.execute(
            text(f"DELETE FROM {table} WHERE thread_id = :thread_id"),
            {"thread_id": provider_session_id},
        )


async def _purge_adk(
    session: AsyncSession,
    provider_session_id: str,
    provider_meta: dict,
) -> None:
    app_name = str(provider_meta.get("app_name") or "agent-base")
    adk_user_id = str(provider_meta.get("adk_user_id") or provider_session_id)
    await session.execute(
        text(
            """
            DELETE FROM events
            WHERE app_name = :app_name
              AND user_id = :user_id
              AND session_id = :session_id
            """
        ),
        {
            "app_name": app_name,
            "user_id": adk_user_id,
            "session_id": provider_session_id,
        },
    )
    await session.execute(
        text(
            """
            DELETE FROM sessions
            WHERE app_name = :app_name
              AND user_id = :user_id
              AND id = :session_id
            """
        ),
        {
            "app_name": app_name,
            "user_id": adk_user_id,
            "session_id": provider_session_id,
        },
    )


async def purge_deleted_threads(
    *,
    dsn: str,
    retention_days: int,
    dry_run: bool,
    hard_delete: bool,
) -> int:
    engine = create_async_engine(dsn, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    purged = 0

    async with session_factory() as session:
        result = await session.execute(
            select(ChatThreadRow).where(
                ChatThreadRow.deleted_at.is_not(None),
                ChatThreadRow.deleted_at < cutoff,
                ChatThreadRow.purged_at.is_(None),
            )
        )
        rows = result.scalars().all()
        for row in rows:
            logger.info(
                "purging thread id=%s type=%s provider_session_id=%s",
                row.id,
                row.thread_type,
                row.provider_session_id,
            )
            if dry_run:
                purged += 1
                continue
            try:
                if row.thread_type == "langgraph":
                    await _purge_langgraph(session, row.provider_session_id)
                elif row.thread_type == "adk":
                    await _purge_adk(session, row.provider_session_id, row.provider_meta or {})
                row.purged_at = datetime.now(UTC)
                if hard_delete:
                    await session.delete(row)
                purged += 1
            except Exception:
                logger.exception("failed to purge thread %s", row.id)
        if not dry_run:
            await session.commit()

    await engine.dispose()
    return purged
