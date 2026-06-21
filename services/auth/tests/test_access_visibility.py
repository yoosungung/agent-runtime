"""Auth /verify includes implicit general-agent access from visibility rules."""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from runtime_common.db.models import Base, SourceMetaRow, UserRow
from runtime_common.general_visibility import GeneralVisibility

TEST_DSN = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def auth_fetch_access(monkeypatch):
    import auth.app as auth_module
    from auth.app import app

    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.session_factory = session_factory

    async with session_factory() as session:
        user = UserRow(
            username="bob",
            password_hash="x",
            tenant="acme",
            disabled=False,
            role="user",
            must_change_password=False,
        )
        session.add(user)
        await session.flush()
        session.add(
            SourceMetaRow(
                kind="agent",
                name="public-bot",
                version="v1",
                runtime_pool="agent:compiled_graph",
                deploy_mode="general",
                config={"general": {"system_prompt": "x", "mcp_servers": [], "mcp_tools": []}},
                created_by_user_id=None,
                owner_tenant=None,
                visibility=GeneralVisibility.PUBLIC,
            )
        )
        session.add(
            SourceMetaRow(
                kind="agent",
                name="tenant-bot",
                version="v1",
                runtime_pool="agent:compiled_graph",
                deploy_mode="general",
                config={"general": {"system_prompt": "x", "mcp_servers": [], "mcp_tools": []}},
                created_by_user_id=user.id,
                owner_tenant="acme",
                visibility=GeneralVisibility.TENANT,
            )
        )
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    access = await auth_module._fetch_access(user_id)
    names = {entry.name for entry in access if entry.kind == "agent"}
    assert names == {"public-bot", "tenant-bot"}

    await engine.dispose()
