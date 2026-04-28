from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import select, update

from runtime_common.db import session_scope
from runtime_common.db.models import RefreshTokenRow, UserRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# User management (read-only)
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(request: Request) -> list[dict]:
    """Return all users (password_hash excluded)."""
    session_factory = request.app.state.session_factory
    async with session_scope(session_factory) as session:
        result = await session.execute(select(UserRow).order_by(UserRow.id))
        rows = result.scalars().all()
        return [
            {
                "id": r.id,
                "username": r.username,
                "tenant": r.tenant,
                "disabled": r.disabled,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Session revocation (admin bridge — called by backend BFF)
# ---------------------------------------------------------------------------


@router.post("/revoke-tokens", status_code=204)
async def revoke_tokens(user_id: int, request: Request) -> None:
    """Revoke all active refresh tokens for a user. Called by admin backend on password change,
    account disable, is_admin revoke, or user delete."""
    session_factory = request.app.state.session_factory
    now = datetime.now(tz=UTC)
    async with session_scope(session_factory) as session:
        await session.execute(
            update(RefreshTokenRow)
            .where(RefreshTokenRow.user_id == user_id, RefreshTokenRow.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    # Invalidate access cache so next /verify re-fetches
    cache = getattr(request.app.state, "access_cache", None)
    if cache is not None:
        cache.set(user_id, [])

    logger.info("tokens_revoked", extra={"user_id": user_id})


@router.post("/invalidate-access", status_code=204)
async def invalidate_access(user_id: int, request: Request) -> None:
    """Drop the cached access list for a user. Called by admin backend after
    grant/revoke writes so the next /verify re-reads `user_resource_access`
    instead of returning the pre-grant snapshot for the cache TTL window."""
    cache = getattr(request.app.state, "access_cache", None)
    if cache is not None:
        cache.invalidate(user_id)
    logger.info("access_invalidated", extra={"user_id": user_id})
