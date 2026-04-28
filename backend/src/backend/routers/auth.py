from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.csrf import generate_csrf_token
from backend.deps import get_auth_client, get_db, get_principal, get_settings
from backend.settings import Settings
from runtime_common.auth import AuthClient
from runtime_common.db.models import UserRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    is_admin: bool
    must_change_password: bool
    user_id: int
    tenant: str | None


class MeResponse(BaseModel):
    user_id: int
    username: str
    tenant: str | None
    is_admin: bool
    must_change_password: bool


def _set_auth_cookies(response: Response, settings: Settings, tokens: dict) -> None:
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    secure = settings.SESSION_COOKIE_SECURE

    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=secure,
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/api/auth",
    )
    # Non-httpOnly CSRF cookie for the frontend to read and echo
    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        samesite="strict",
        secure=secure,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.ACCESS_TOKEN_COOKIE)
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE, path="/api/auth")
    response.delete_cookie(settings.CSRF_COOKIE_NAME)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_client: AuthClient = Depends(get_auth_client),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    # Forward to auth service
    try:
        resp = await auth_client._client.post(
            "/login", json={"username": body.username, "password": body.password}
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if 400 <= status < 500:
            try:
                detail = exc.response.json().get("detail", exc.response.text)
            except ValueError:
                detail = exc.response.text or "Auth request rejected"
            raise HTTPException(status_code=status, detail=detail) from exc
        raise HTTPException(status_code=502, detail="Auth service error") from exc

    tokens = resp.json()
    _set_auth_cookies(response, settings, tokens)

    # Read user from DB
    result = await db.execute(
        select(
            UserRow.id,
            UserRow.username,
            UserRow.tenant,
            UserRow.is_admin,
            UserRow.must_change_password,
        ).where(UserRow.username == body.username)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="User not found")

    return LoginResponse(
        username=row.username,
        is_admin=bool(row.is_admin),
        must_change_password=bool(row.must_change_password),
        user_id=row.id,
        tenant=row.tenant,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE)
    if refresh_token:
        try:
            await auth_client.logout(refresh_token)
        except Exception:
            logger.warning("Failed to revoke refresh token during logout", exc_info=True)
    _clear_auth_cookies(response, settings)


me_router = APIRouter(prefix="/api", tags=["auth"])


@me_router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    principal = await get_principal(request, settings)

    result = await db.execute(
        select(
            UserRow.id,
            UserRow.username,
            UserRow.tenant,
            UserRow.is_admin,
            UserRow.must_change_password,
        ).where(UserRow.id == principal.user_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    return MeResponse(
        user_id=row.id,
        username=row.username,
        tenant=row.tenant,
        is_admin=bool(row.is_admin),
        must_change_password=bool(row.must_change_password),
    )
