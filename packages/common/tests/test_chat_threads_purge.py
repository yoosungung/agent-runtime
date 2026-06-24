"""Tests for chat thread purge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.chat_threads_purge import purge_deleted_threads
from runtime_common.db.models import Base, ChatThreadRow, UserRow

TEST_DSN = "sqlite+aiosqlite:///file:chatpurge?mode=memory&cache=shared&uri=true"


@pytest_asyncio.fixture()
async def session_factory():
    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(UserRow(id=1, username="u", password_hash="x", tenant="dev", role="user"))
        session.add(
            ChatThreadRow(
                id="11111111-1111-4111-8111-111111111111",
                user_id=1,
                agent_name="bot",
                agent_version="v1",
                thread_type="custom",
                provider_session_id="sess-1",
                title="t",
                last_message_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                deleted_at=datetime.now(UTC) - timedelta(days=40),
            )
        )
        await session.commit()

    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_purge_marks_custom_thread(session_factory) -> None:
    count = await purge_deleted_threads(
        dsn=TEST_DSN,
        retention_days=30,
        dry_run=False,
        hard_delete=False,
    )
    assert count == 1

    async with session_factory() as session:
        row = (
            await session.execute(
                select(ChatThreadRow).where(
                    ChatThreadRow.id == "11111111-1111-4111-8111-111111111111"
                )
            )
        ).scalar_one()
        assert row.purged_at is not None
