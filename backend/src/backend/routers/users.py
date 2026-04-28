from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.deps import (
    check_csrf,
    get_auth_client,
    get_db,
    get_principal,
    get_settings,
    require_admin,
)
from backend.passwords import check_policy, hash_password, verify_password
from backend.settings import Settings
from runtime_common.auth import AuthClient
from runtime_common.db.models import SourceMetaRow, UserResourceAccessRow, UserRow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
)

RE_USERNAME = re.compile(r"^[a-zA-Z0-9_.-]{3,128}$")

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    id: int
    username: str
    tenant: str | None
    disabled: bool
    is_admin: bool
    must_change_password: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class AccessItem(BaseModel):
    kind: str
    name: str
    created_at: datetime


class AccessListResponse(BaseModel):
    items: list[AccessItem]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_username(username: str) -> None:
    if not RE_USERNAME.match(username):
        raise HTTPException(
            status_code=400,
            detail="username must match ^[a-zA-Z0-9_.-]{3,128}$",
        )


async def _count_active_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(UserRow)
        .where(UserRow.is_admin == True, UserRow.disabled == False)  # noqa: E712
    )
    return result.scalar_one()


async def _revoke_tokens_safe(auth_client: AuthClient, user_id: int) -> None:
    try:
        await auth_client.revoke_tokens(user_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to revoke tokens for user {user_id}: {exc}",
        ) from exc


async def _invalidate_access_safe(auth_client: AuthClient, user_id: int) -> None:
    """Best-effort cache invalidation. The auth-side access cache has a 5s TTL
    that self-heals, so a missed invalidation only delays consistency briefly
    rather than corrupting it — log and continue instead of 500-ing the write."""
    try:
        await auth_client.invalidate_access(user_id)
    except Exception as exc:
        logger.warning(
            "invalidate_access_failed",
            extra={"event_user_id": user_id, "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# GET /api/users
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=UserListResponse,
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)
async def list_users(
    username: str | None = Query(None, description="Username prefix filter"),
    tenant: str | None = Query(None),
    disabled: bool | None = Query(None),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    limit = min(limit, 100)
    q = select(UserRow)
    count_q = select(func.count()).select_from(UserRow)

    if username is not None:
        q = q.where(UserRow.username.like(f"{username}%"))
        count_q = count_q.where(UserRow.username.like(f"{username}%"))
    if tenant is not None:
        q = q.where(UserRow.tenant == tenant)
        count_q = count_q.where(UserRow.tenant == tenant)
    if disabled is not None:
        q = q.where(UserRow.disabled == disabled)
        count_q = count_q.where(UserRow.disabled == disabled)

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.order_by(UserRow.username.asc()).limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /api/users/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/{id}",
    response_model=UserResponse,
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)
async def get_user(
    id: int,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    result = await db.execute(select(UserRow).where(UserRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(row)


# ---------------------------------------------------------------------------
# POST /api/users
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    username: str
    password: str
    tenant: str | None = None
    is_admin: bool = False


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
    dependencies=[Depends(check_csrf)],
)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    _validate_username(body.username)
    try:
        check_policy(body.password, settings.PASSWORD_MIN_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    hashed = hash_password(body.password)
    row = UserRow(
        username=body.username,
        password_hash=hashed,
        tenant=body.tenant,
        disabled=False,
        is_admin=body.is_admin,
        must_change_password=False,
    )
    db.add(row)
    db.add(make_audit_row("user.create", principal.user_id, principal.sub, username=body.username))
    try:
        await db.flush()
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Username '{body.username}' already exists"
        ) from exc

    log_event(
        "user.create",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=row.id,
        username=row.username,
    )

    return UserResponse.model_validate(row)


# ---------------------------------------------------------------------------
# PATCH /api/users/{id}
# ---------------------------------------------------------------------------


class UserPatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tenant: str | None = None
    disabled: bool | None = None
    is_admin: bool | None = None


@router.patch(
    "/{id}",
    response_model=UserResponse,
    dependencies=[Depends(check_csrf)],
)
async def patch_user(
    id: int,
    body: UserPatchRequest,
    request: Request,
    if_match: Annotated[str | None, Header(alias="if-match")] = None,
    db: AsyncSession = Depends(get_db),
    auth_client: AuthClient = Depends(get_auth_client),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(select(UserRow).where(UserRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Optimistic locking: if If-Match header present, compare with updated_at epoch
    if if_match is not None:
        try:
            expected_ts = int(if_match)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="If-Match must be an integer epoch timestamp"
            ) from exc
        actual_ts = int(row.updated_at.timestamp())
        if expected_ts != actual_ts:
            raise HTTPException(
                status_code=412,
                detail="Precondition Failed: resource was modified by another request",
            )

    # Self-lockout protection
    if id == principal.user_id:
        if body.is_admin is False:
            raise HTTPException(status_code=400, detail="Cannot revoke your own admin privileges")
        if body.disabled is True:
            raise HTTPException(status_code=400, detail="Cannot disable your own account")

    # Last admin protection
    is_admin_revoke = body.is_admin is False and row.is_admin
    is_disabling = body.disabled is True and not row.disabled
    if is_admin_revoke or (is_disabling and row.is_admin):
        active_admin_count = await _count_active_admins(db)
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last active admin",
            )

    # Track what requires token revocation
    needs_revoke = False
    if body.disabled is True and not row.disabled:
        needs_revoke = True
    if body.is_admin is False and row.is_admin:
        needs_revoke = True

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    row.updated_at = datetime.now(UTC)

    db.add(
        make_audit_row(
            "user.patch",
            principal.user_id,
            principal.sub,
            user_id=id,
            changed_fields=list(update_data.keys()),
        )
    )
    await db.flush()

    if needs_revoke:
        await _revoke_tokens_safe(auth_client, id)

    await db.commit()
    await db.refresh(row)

    log_event(
        "user.patch",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
        changed_fields=list(update_data.keys()),
    )

    return UserResponse.model_validate(row)


# ---------------------------------------------------------------------------
# POST /api/users/{id}/password  (admin force change)
# ---------------------------------------------------------------------------


class PasswordChangeRequest(BaseModel):
    password: str
    must_change_password: bool = True


@router.post(
    "/{id}/password",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def set_user_password(
    id: int,
    body: PasswordChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_client: AuthClient = Depends(get_auth_client),
    settings: Settings = Depends(get_settings),
) -> None:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        check_policy(body.password, settings.PASSWORD_MIN_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(select(UserRow).where(UserRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    row.password_hash = hash_password(body.password)
    row.must_change_password = body.must_change_password
    row.updated_at = datetime.now(UTC)

    db.add(make_audit_row("user.password_reset", principal.user_id, principal.sub, user_id=id))
    await db.flush()
    await _revoke_tokens_safe(auth_client, id)
    await db.commit()

    log_event(
        "user.password_reset",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
    )


# ---------------------------------------------------------------------------
# POST /api/me/password  (self change)
# ---------------------------------------------------------------------------

me_router = APIRouter(prefix="/api/me", tags=["users"])


class SelfPasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@me_router.post(
    "/password",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def change_own_password(
    body: SelfPasswordChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_client: AuthClient = Depends(get_auth_client),
    settings: Settings = Depends(get_settings),
) -> None:
    principal = await get_principal(request, settings)

    try:
        check_policy(body.new_password, settings.PASSWORD_MIN_LENGTH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(select(UserRow).where(UserRow.id == principal.user_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(row.password_hash, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    row.password_hash = hash_password(body.new_password)
    row.must_change_password = False
    row.updated_at = datetime.now(UTC)

    db.add(
        make_audit_row(
            "user.password_change", principal.user_id, principal.sub, user_id=principal.user_id
        )
    )
    await db.flush()
    await _revoke_tokens_safe(auth_client, principal.user_id)
    await db.commit()

    log_event(
        "user.password_change",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=principal.user_id,
    )


# ---------------------------------------------------------------------------
# DELETE /api/users/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{id}",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def delete_user(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_client: AuthClient = Depends(get_auth_client),
    settings: Settings = Depends(get_settings),
) -> None:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    if id == principal.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    result = await db.execute(select(UserRow).where(UserRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Last admin protection
    if row.is_admin and not row.disabled:
        active_admin_count = await _count_active_admins(db)
        if active_admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last active admin")

    username = row.username
    await _revoke_tokens_safe(auth_client, id)
    db.add(
        make_audit_row(
            "user.delete", principal.user_id, principal.sub, user_id=id, username=row.username
        )
    )
    await db.delete(row)
    await db.commit()

    log_event(
        "user.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
        username=username,
    )


# ---------------------------------------------------------------------------
# GET /api/users/{id}/access
# ---------------------------------------------------------------------------


@router.get(
    "/{id}/access",
    response_model=AccessListResponse,
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)
async def list_user_access(
    id: int,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AccessListResponse:
    limit = min(limit, 100)

    # Verify user exists
    result = await db.execute(select(UserRow).where(UserRow.id == id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    count_q = (
        select(func.count())
        .select_from(UserResourceAccessRow)
        .where(UserResourceAccessRow.user_id == id)
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = (
        select(UserResourceAccessRow)
        .where(UserResourceAccessRow.user_id == id)
        .order_by(UserResourceAccessRow.kind.asc(), UserResourceAccessRow.name.asc())
        .limit(limit)
        .offset(offset)
    )
    result2 = await db.execute(q)
    rows = result2.scalars().all()

    return AccessListResponse(
        items=[AccessItem(kind=r.kind, name=r.name, created_at=r.created_at) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# POST /api/users/{id}/access
# ---------------------------------------------------------------------------


class GrantAccessRequest(BaseModel):
    kind: str
    name: str


@router.post(
    "/{id}/access",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def grant_user_access(
    id: int,
    body: GrantAccessRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify user exists
    result = await db.execute(select(UserRow).where(UserRow.id == id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check source_meta.name exists
    sm_result = await db.execute(
        select(func.count())
        .select_from(SourceMetaRow)
        .where(SourceMetaRow.kind == body.kind, SourceMetaRow.name == body.name)
    )
    if sm_result.scalar_one() == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No source_meta found with kind={body.kind}, name={body.name}",
        )

    # Idempotent insert
    existing = await db.execute(
        select(UserResourceAccessRow).where(
            UserResourceAccessRow.user_id == id,
            UserResourceAccessRow.kind == body.kind,
            UserResourceAccessRow.name == body.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return  # Already exists, idempotent 204

    row = UserResourceAccessRow(user_id=id, kind=body.kind, name=body.name)
    db.add(row)
    db.add(
        make_audit_row(
            "access.grant",
            principal.user_id,
            principal.sub,
            user_id=id,
            kind=body.kind,
            name=body.name,
        )
    )
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race condition duplicate — idempotent
        return

    await _invalidate_access_safe(auth_client, id)

    log_event(
        "access.grant",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
        kind=body.kind,
        name=body.name,
    )


# ---------------------------------------------------------------------------
# DELETE /api/users/{id}/access
# ---------------------------------------------------------------------------


@router.delete(
    "/{id}/access",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def revoke_user_access(
    id: int,
    request: Request,
    kind: str = Query(...),
    name: str = Query(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(
        select(UserResourceAccessRow).where(
            UserResourceAccessRow.user_id == id,
            UserResourceAccessRow.kind == kind,
            UserResourceAccessRow.name == name,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Access entry not found")

    db.add(
        make_audit_row(
            "access.revoke", principal.user_id, principal.sub, user_id=id, kind=kind, name=name
        )
    )
    await db.delete(row)
    await db.commit()

    await _invalidate_access_safe(auth_client, id)

    log_event(
        "access.revoke",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
        kind=kind,
        name=name,
    )


# ---------------------------------------------------------------------------
# POST /api/users/{id}/access:bulk
# ---------------------------------------------------------------------------


class BulkAccessItem(BaseModel):
    kind: str
    name: str


class BulkAccessRequest(BaseModel):
    action: Literal["grant", "revoke"]
    items: list[BulkAccessItem]


@router.post(
    "/{id}/access:bulk",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def bulk_user_access(
    id: int,
    body: BulkAccessRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    principal = await get_principal(request, settings)
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verify user exists
    result = await db.execute(select(UserRow).where(UserRow.id == id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="User not found")

    if body.action == "grant":
        for item in body.items:
            existing = await db.execute(
                select(UserResourceAccessRow).where(
                    UserResourceAccessRow.user_id == id,
                    UserResourceAccessRow.kind == item.kind,
                    UserResourceAccessRow.name == item.name,
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(UserResourceAccessRow(user_id=id, kind=item.kind, name=item.name))
        db.add(
            make_audit_row(
                f"access.bulk_{body.action}",
                principal.user_id,
                principal.sub,
                user_id=id,
                count=len(body.items),
            )
        )
        try:
            await db.flush()
            await db.commit()
        except IntegrityError:
            await db.rollback()
    else:  # revoke
        for item in body.items:
            result2 = await db.execute(
                select(UserResourceAccessRow).where(
                    UserResourceAccessRow.user_id == id,
                    UserResourceAccessRow.kind == item.kind,
                    UserResourceAccessRow.name == item.name,
                )
            )
            row2 = result2.scalar_one_or_none()
            if row2 is not None:
                await db.delete(row2)
        db.add(
            make_audit_row(
                f"access.bulk_{body.action}",
                principal.user_id,
                principal.sub,
                user_id=id,
                count=len(body.items),
            )
        )
        await db.commit()

    await _invalidate_access_safe(auth_client, id)

    log_event(
        f"access.bulk_{body.action}",
        actor_id=principal.user_id,
        actor=principal.sub,
        user_id=id,
        count=len(body.items),
    )
