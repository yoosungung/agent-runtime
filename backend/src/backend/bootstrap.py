from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.passwords import hash_password
from runtime_common.db.models import UserRow

logger = logging.getLogger(__name__)


async def run_bootstrap(session: AsyncSession, settings) -> None:
    """Create initial admin user if users table is empty."""
    count_result = await session.execute(select(func.count()).select_from(UserRow))
    count = count_result.scalar_one()
    if count > 0:
        logger.debug("Bootstrap skipped — users table is not empty (%d rows)", count)
        return

    # Read password from file first, then env
    # Note: file I/O here is intentionally synchronous (startup path, small file)
    password: str | None = None
    password_file = settings.INITIAL_ADMIN_PASSWORD_FILE
    if password_file:
        p = Path(password_file)
        if p.exists():  # noqa: ASYNC240
            password = p.read_text().strip()  # noqa: ASYNC240

    if not password:
        password = settings.INITIAL_ADMIN_PASSWORD or None

    if not password:
        logger.warning(
            "Bootstrap skipped — no INITIAL_ADMIN_PASSWORD or password file found. "
            "Set INITIAL_ADMIN_PASSWORD_FILE or INITIAL_ADMIN_PASSWORD to seed the first admin."
        )
        return

    username = settings.INITIAL_ADMIN_USERNAME or "admin"
    hashed = hash_password(password)

    admin = UserRow(
        username=username,
        password_hash=hashed,
        tenant=None,
        disabled=False,
        is_admin=True,
        must_change_password=True,
    )
    session.add(admin)
    await session.flush()
    logger.info("Bootstrap: created initial admin user '%s' (id=%d)", username, admin.id)
