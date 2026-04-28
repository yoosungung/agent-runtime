from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import check_csrf, get_db, require_admin
from runtime_common.db.models import SourceMetaRow, UserMetaRow

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/user-meta",
    tags=["user-meta"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

RE_SECRETS_REF = re.compile(r"^(vault|env|aws-sm)://.+$")
MAX_CONFIG_BYTES = 64 * 1024


class UserMetaResponse(BaseModel):
    id: int
    source_meta_id: int
    principal_id: str
    config: dict
    secrets_ref: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserMetaListResponse(BaseModel):
    items: list[UserMetaResponse]
    total: int
    limit: int
    offset: int


class UserMetaUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    source_meta_id: int
    principal_id: str
    config: dict | None = None
    secrets_ref: str | None = None


def _validate_secrets_ref(secrets_ref: str | None) -> None:
    if secrets_ref is not None and not RE_SECRETS_REF.match(secrets_ref):
        raise HTTPException(
            status_code=400,
            detail="secrets_ref must match ^(vault|env|aws-sm)://.+$",
        )


def _validate_config(config: dict | None) -> None:
    if config is None:
        return
    import json

    serialized = json.dumps(config)
    if len(serialized.encode()) > MAX_CONFIG_BYTES:
        raise HTTPException(status_code=413, detail="config exceeds 64KB limit")


@router.get("", response_model=UserMetaListResponse)
async def list_user_meta(
    source_meta_id: int | None = Query(None),
    principal_id: str | None = Query(None),
    kind: str | None = Query(None),
    name: str | None = Query(None),
    version: str | None = Query(None),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> UserMetaListResponse:
    limit = min(limit, 100)
    q = select(UserMetaRow)

    if source_meta_id is not None:
        q = q.where(UserMetaRow.source_meta_id == source_meta_id)
    elif kind is not None and name is not None and version is not None:
        # Join with source_meta to filter by kind/name/version
        sm_q = select(SourceMetaRow.id).where(
            SourceMetaRow.kind == kind,
            SourceMetaRow.name == name,
            SourceMetaRow.version == version,
        )
        sm_result = await db.execute(sm_q)
        sm_ids = [r[0] for r in sm_result.all()]
        if not sm_ids:
            return UserMetaListResponse(items=[], total=0, limit=limit, offset=offset)
        q = q.where(UserMetaRow.source_meta_id.in_(sm_ids))

    if principal_id is not None:
        q = q.where(UserMetaRow.principal_id == principal_id)

    from sqlalchemy import func

    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.scalars().all()

    return UserMetaListResponse(
        items=[UserMetaResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.put("", response_model=UserMetaResponse, status_code=200)
async def upsert_user_meta(
    body: UserMetaUpsertRequest,
    db: AsyncSession = Depends(get_db),
) -> UserMetaResponse:
    _validate_config(body.config)
    _validate_secrets_ref(body.secrets_ref)

    # Verify source_meta exists
    sm_result = await db.execute(
        select(SourceMetaRow).where(SourceMetaRow.id == body.source_meta_id)
    )
    if sm_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="source_meta not found")

    # Try to get existing row
    existing_result = await db.execute(
        select(UserMetaRow).where(
            UserMetaRow.source_meta_id == body.source_meta_id,
            UserMetaRow.principal_id == body.principal_id,
        )
    )
    row = existing_result.scalar_one_or_none()

    if row is None:
        row = UserMetaRow(
            source_meta_id=body.source_meta_id,
            principal_id=body.principal_id,
            config=body.config or {},
            secrets_ref=body.secrets_ref,
        )
        db.add(row)
    else:
        if body.config is not None:
            row.config = body.config
        if body.secrets_ref is not None:
            row.secrets_ref = body.secrets_ref
        row.updated_at = datetime.now(UTC)

    await db.flush()
    await db.commit()
    await db.refresh(row)
    return UserMetaResponse.model_validate(row)


@router.delete("/{id}", status_code=204)
async def delete_user_meta(
    id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(UserMetaRow).where(UserMetaRow.id == id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user_meta not found")
    await db.delete(row)
    await db.commit()
