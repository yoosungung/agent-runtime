from __future__ import annotations

import logging

import httpx
from fastapi import Depends, HTTPException, Request  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession

from backend.csrf import validate_csrf
from backend.settings import Settings
from backend.settings import get_settings as _get_settings
from runtime_common.auth import AuthClient
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)


def get_settings() -> Settings:
    return _get_settings()


async def get_db(request: Request) -> AsyncSession:  # type: ignore[return]
    async with request.app.state.session_factory() as session:
        yield session


def get_auth_client(request: Request) -> AuthClient:
    return request.app.state.auth_client


async def get_principal(
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Principal:
    auth_client: AuthClient = request.app.state.auth_client
    access_cookie = settings.ACCESS_TOKEN_COOKIE
    refresh_cookie = settings.REFRESH_TOKEN_COOKIE

    token: str | None = request.cookies.get(access_cookie)

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    principal: Principal | None = None

    try:
        principal = await auth_client.verify(token, grace_sec=0)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 401:
            raise HTTPException(status_code=502, detail="Auth service error") from exc

        # Try to refresh
        refresh_token: str | None = request.cookies.get(refresh_cookie)
        if not refresh_token:
            raise HTTPException(  # noqa: B904
                status_code=401, detail="Token expired, no refresh token"
            )

        try:
            tokens = await auth_client.refresh(refresh_token)
        except httpx.HTTPStatusError:
            raise HTTPException(  # noqa: B904
                status_code=401, detail="Refresh token expired or invalid"
            )

        new_access = tokens.get("access_token", "")
        new_refresh = tokens.get("refresh_token", refresh_token)

        # Store new tokens on response — attach to request state for downstream use
        request.state.new_access_token = new_access
        request.state.new_refresh_token = new_refresh

        try:
            principal = await auth_client.verify(new_access, grace_sec=0)
        except httpx.HTTPStatusError:
            raise HTTPException(  # noqa: B904
                status_code=401, detail="Could not verify refreshed token"
            )

    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return principal


async def require_admin(principal: Principal = Depends(get_principal)) -> Principal:  # noqa: B008
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return principal


async def check_csrf(
    request: Request,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    """CSRF check for state-changing methods."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    header_val = request.headers.get("X-CSRF-Token")
    cookie_val = request.cookies.get(settings.CSRF_COOKIE_NAME)
    if not validate_csrf(header_val, cookie_val):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
