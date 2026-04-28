from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import check_csrf, get_db, require_admin
from runtime_common.db.models import AuditLogRow

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)


class AuditLogResponse(BaseModel):
    id: int
    action: str
    actor_id: int
    actor: str
    details: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditLogListResponse)
async def list_audit_log(
    actor_id: int | None = Query(None, description="Filter by actor user ID"),
    action: str | None = Query(None, description="Filter by action prefix"),
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    limit = min(limit, 200)

    q = select(AuditLogRow).order_by(AuditLogRow.created_at.desc())
    count_q = select(func.count()).select_from(AuditLogRow)

    if actor_id is not None:
        q = q.where(AuditLogRow.actor_id == actor_id)
        count_q = count_q.where(AuditLogRow.actor_id == actor_id)
    if action is not None:
        q = q.where(AuditLogRow.action.like(f"{action}%"))
        count_q = count_q.where(AuditLogRow.action.like(f"{action}%"))

    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    rows = result.scalars().all()

    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
