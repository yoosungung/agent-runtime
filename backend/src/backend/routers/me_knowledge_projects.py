"""Read-only pipeline project APIs for general-agent knowledge binding (any authenticated user)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.deps import get_principal, get_settings
from backend.pipeline_project_read import (
    ProjectsListReadResponse,
    get_tenant_project_binding,
    list_tenant_projects,
    project_store,
    require_tenant,
)
from backend.settings import Settings
from runtime_common.schemas import Principal

router = APIRouter(
    prefix="/api/me/knowledge-projects",
    tags=["me-knowledge-projects"],
    dependencies=[Depends(get_principal)],
)


@router.get("", response_model=ProjectsListReadResponse)
async def list_my_knowledge_projects(
    principal: Principal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ProjectsListReadResponse:
    tenant = require_tenant(principal)
    store = project_store(settings)
    return await list_tenant_projects(tenant=tenant, store=store)


@router.get("/{project_id}/binding")
async def get_my_knowledge_project_binding(
    project_id: str,
    principal: Principal = Depends(get_principal),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    tenant = require_tenant(principal)
    store = project_store(settings)
    return await get_tenant_project_binding(
        tenant=tenant,
        project_id=project_id,
        store=store,
    )
