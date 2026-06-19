from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import check_csrf, get_db, get_principal, get_settings
from backend.pool_status import PoolRuntimeStatus, fetch_pool_summary
from backend.settings import Settings
from runtime_common.db.models import SourceMetaRow

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_principal), Depends(check_csrf)],
)


class ResourceStatusCounts(BaseModel):
    total: int = 0
    active: int = 0
    pending: int = 0
    failed: int = 0
    retired: int = 0


class ResourceSummary(BaseModel):
    agent: ResourceStatusCounts = Field(default_factory=ResourceStatusCounts)
    mcp: ResourceStatusCounts = Field(default_factory=ResourceStatusCounts)


class RecentIssue(BaseModel):
    id: int
    kind: str
    name: str
    version: str
    status: str
    deploy_mode: str
    created_at: datetime


class PoolRuntimeStatusResponse(BaseModel):
    runtime_kind: str
    pod_count: int
    active_requests: int
    max_capacity: int


class PoolSummaryResponse(BaseModel):
    available: bool
    error: str | None = None
    agents: list[PoolRuntimeStatusResponse] = Field(default_factory=list)
    mcp: list[PoolRuntimeStatusResponse] = Field(default_factory=list)


class DashboardSummaryResponse(BaseModel):
    resources: ResourceSummary
    recent_issues: list[RecentIssue]
    pools: PoolSummaryResponse


def _empty_counts() -> ResourceStatusCounts:
    return ResourceStatusCounts()


async def _resource_summary(db: AsyncSession) -> ResourceSummary:
    summary = ResourceSummary()

    total_q = (
        select(SourceMetaRow.kind, func.count())
        .group_by(SourceMetaRow.kind)
    )
    for kind, count in (await db.execute(total_q)).all():
        counts = summary.agent if kind == "agent" else summary.mcp
        counts.total = count

    active_q = (
        select(SourceMetaRow.kind, func.count())
        .where(SourceMetaRow.status == "active", SourceMetaRow.retired.is_(False))
        .group_by(SourceMetaRow.kind)
    )
    for kind, count in (await db.execute(active_q)).all():
        counts = summary.agent if kind == "agent" else summary.mcp
        counts.active = count

    pending_q = (
        select(SourceMetaRow.kind, func.count())
        .where(SourceMetaRow.status == "pending")
        .group_by(SourceMetaRow.kind)
    )
    for kind, count in (await db.execute(pending_q)).all():
        counts = summary.agent if kind == "agent" else summary.mcp
        counts.pending = count

    failed_q = (
        select(SourceMetaRow.kind, func.count())
        .where(SourceMetaRow.status == "failed")
        .group_by(SourceMetaRow.kind)
    )
    for kind, count in (await db.execute(failed_q)).all():
        counts = summary.agent if kind == "agent" else summary.mcp
        counts.failed = count

    retired_q = (
        select(SourceMetaRow.kind, func.count())
        .where(or_(SourceMetaRow.retired.is_(True), SourceMetaRow.status == "retired"))
        .group_by(SourceMetaRow.kind)
    )
    for kind, count in (await db.execute(retired_q)).all():
        counts = summary.agent if kind == "agent" else summary.mcp
        counts.retired = count

    return summary


async def _recent_issues(db: AsyncSession, limit: int = 10) -> list[RecentIssue]:
    q = (
        select(SourceMetaRow)
        .where(SourceMetaRow.status.in_(("pending", "failed")))
        .order_by(SourceMetaRow.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        RecentIssue(
            id=row.id,
            kind=row.kind,
            name=row.name,
            version=row.version,
            status=row.status,
            deploy_mode=row.deploy_mode,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _pool_response(pool: PoolRuntimeStatus) -> PoolRuntimeStatusResponse:
    return PoolRuntimeStatusResponse(
        runtime_kind=pool.runtime_kind,
        pod_count=pool.pod_count,
        active_requests=pool.active_requests,
        max_capacity=pool.max_capacity,
    )


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DashboardSummaryResponse:
    resources = await _resource_summary(db)
    recent_issues = await _recent_issues(db)
    pools = await fetch_pool_summary(settings.REDIS_URL)

    return DashboardSummaryResponse(
        resources=resources,
        recent_issues=recent_issues,
        pools=PoolSummaryResponse(
            available=pools.available,
            error=pools.error,
            agents=[_pool_response(p) for p in pools.agents],
            mcp=[_pool_response(p) for p in pools.mcp],
        ),
    )
