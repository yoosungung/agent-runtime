from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update

from runtime_common.db import session_scope
from runtime_common.db.models import ApiKeyRow, RefreshTokenRow, UserRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])
_ph = PasswordHasher()


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


# ---------------------------------------------------------------------------
# API keys (admin bridge — called by backend BFF)
# ---------------------------------------------------------------------------


class CreateApiKeyRequest(BaseModel):
    user_id: int
    name: str
    expires_in_days: int | None = None


class ApiKeyListItem(BaseModel):
    id: int
    name: str
    created_at: datetime
    expires_at: datetime | None
    disabled: bool


@router.post("/api-keys", status_code=201)
async def create_api_key(req: CreateApiKeyRequest, request: Request) -> dict:
    """Create a user-bound API key. Plain key is returned once."""
    secret = secrets.token_hex(32)
    key_hash = _ph.hash(secret)
    expires_at: datetime | None = None
    if req.expires_in_days is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(days=req.expires_in_days)

    session_factory = request.app.state.session_factory
    async with session_scope(session_factory) as session:
        user_result = await session.execute(select(UserRow).where(UserRow.id == req.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or user.disabled:
            raise HTTPException(status_code=400, detail="user not found or disabled")

        row = ApiKeyRow(
            user_id=user.id,
            key_hash=key_hash,
            name=req.name,
            tenant=user.tenant,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        row_id = row.id

    plain_key = f"ak_{row_id}_{secret}"
    logger.info(
        "api_key_created",
        extra={"key_name": req.name, "key_id": row_id, "user_id": req.user_id},
    )
    return {"key": plain_key, "id": row_id, "name": req.name}


@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_api_keys(user_id: int, request: Request) -> list[ApiKeyListItem]:
    session_factory = request.app.state.session_factory
    async with session_scope(session_factory) as session:
        result = await session.execute(
            select(ApiKeyRow)
            .where(ApiKeyRow.user_id == user_id)
            .order_by(ApiKeyRow.created_at.desc())
        )
        rows = result.scalars().all()
    return [
        ApiKeyListItem(
            id=r.id,
            name=r.name,
            created_at=r.created_at,
            expires_at=r.expires_at,
            disabled=r.disabled,
        )
        for r in rows
    ]


@router.delete("/api-keys/{key_id}", status_code=204)
async def disable_api_key(key_id: int, user_id: int, request: Request) -> None:
    session_factory = request.app.state.session_factory
    async with session_scope(session_factory) as session:
        result = await session.execute(
            select(ApiKeyRow).where(ApiKeyRow.id == key_id, ApiKeyRow.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="api key not found")
        if not row.disabled:
            row.disabled = True
    logger.info("api_key_disabled", extra={"id": key_id, "user_id": user_id})
