"""Cluster-internal pipeline APIs for agent-pool (binding resolve)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.deps import get_settings
from backend.pipeline_project_read import get_tenant_project_binding, project_store
from backend.settings import Settings

router = APIRouter(prefix="/internal/v1/pipeline", tags=["pipeline-internal"])


def require_agent_pool_caller(request: Request) -> None:
    if request.headers.get("X-Runtime-Caller") != "agent-pool":
        raise HTTPException(status_code=403, detail="forbidden")


@router.get(
    "/tenants/{tenant}/projects/{project_id}/binding",
    dependencies=[Depends(require_agent_pool_caller)],
)
async def internal_project_binding(
    tenant: str,
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    store = project_store(settings)
    return await get_tenant_project_binding(
        tenant=tenant,
        project_id=project_id,
        store=store,
    )
