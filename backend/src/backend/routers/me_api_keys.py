from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.deps import check_csrf, get_auth_client, get_principal
from runtime_common.auth import AuthClient
from runtime_common.schemas import Principal

router = APIRouter(
    prefix="/api/me/api-keys",
    tags=["me-api-keys"],
    dependencies=[Depends(get_principal), Depends(check_csrf)],
)


class ApiKeyListItem(BaseModel):
    id: int
    name: str
    created_at: datetime
    expires_at: datetime | None
    disabled: bool


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyListItem]
    total: int


class ApiKeyCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=128)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyCreateResponse(BaseModel):
    id: int
    name: str
    key: str


@router.get("", response_model=ApiKeyListResponse)
async def list_my_api_keys(
    principal: Principal = Depends(get_principal),
    auth_client: AuthClient = Depends(get_auth_client),
) -> ApiKeyListResponse:
    items = await auth_client.list_api_keys(principal.user_id)
    parsed = [ApiKeyListItem.model_validate(item) for item in items]
    return ApiKeyListResponse(items=parsed, total=len(parsed))


@router.post("", response_model=ApiKeyCreateResponse, status_code=201)
async def create_my_api_key(
    body: ApiKeyCreateRequest,
    principal: Principal = Depends(get_principal),
    auth_client: AuthClient = Depends(get_auth_client),
) -> ApiKeyCreateResponse:
    try:
        created = await auth_client.create_api_key(
            user_id=principal.user_id,
            name=body.name.strip(),
            expires_in_days=body.expires_in_days,
        )
    except Exception as exc:
        from httpx import HTTPStatusError

        if isinstance(exc, HTTPStatusError) and exc.response.status_code == 400:
            raise HTTPException(status_code=400, detail="Cannot create API key for this user") from exc
        raise HTTPException(status_code=502, detail="Auth service error") from exc
    return ApiKeyCreateResponse(id=created["id"], name=created["name"], key=created["key"])


@router.delete("/{key_id}", status_code=204)
async def disable_my_api_key(
    key_id: int,
    principal: Principal = Depends(get_principal),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    try:
        await auth_client.disable_api_key(principal.user_id, key_id)
    except Exception as exc:
        from httpx import HTTPStatusError

        if isinstance(exc, HTTPStatusError) and exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="API key not found") from exc
        raise HTTPException(status_code=502, detail="Auth service error") from exc
