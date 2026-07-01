"""Tenant-scoped read-only pipeline project helpers (admin + user APIs)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from path_graph.admin.lifecycle import api_get_binding
from path_graph.admin.projects import ProjectStore
from path_graph.contracts.project import ProjectProfile
from pydantic import BaseModel

from backend.settings import Settings
from runtime_common.schemas import Principal


class ProjectReadResponse(BaseModel):
    tenant: str
    id: str
    slug: str
    name: str
    created_at: str | None = None

    @classmethod
    def from_profile(cls, profile: ProjectProfile) -> ProjectReadResponse:
        return cls(
            tenant=profile.tenant,
            id=profile.id,
            slug=profile.slug,
            name=profile.name,
            created_at=profile.created_at.isoformat() if profile.created_at else None,
        )


class ProjectsListReadResponse(BaseModel):
    items: list[ProjectReadResponse]


def path_graph_dsn(settings: Settings) -> str:
    dsn = settings.PATH_GRAPH_DSN or settings.POSTGRES_DSN
    if not dsn:
        raise HTTPException(status_code=503, detail="PATH_GRAPH_DSN not configured")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def require_tenant(principal: Principal) -> str:
    tenant = (principal.tenant or "").strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="User tenant not set")
    return tenant


def project_store(settings: Settings) -> ProjectStore:
    return ProjectStore(path_graph_dsn(settings))


async def list_tenant_projects(
    *,
    tenant: str,
    store: ProjectStore,
) -> ProjectsListReadResponse:
    profiles = await asyncio.to_thread(store.list_projects, tenant)
    return ProjectsListReadResponse(
        items=[ProjectReadResponse.from_profile(p) for p in profiles],
    )


async def require_tenant_project(
    *,
    tenant: str,
    project_id: str,
    store: ProjectStore,
) -> ProjectProfile:
    profile = await asyncio.to_thread(store.get_project, tenant, project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return profile


async def get_tenant_project_binding(
    *,
    tenant: str,
    project_id: str,
    store: ProjectStore,
) -> dict[str, Any]:
    await require_tenant_project(tenant=tenant, project_id=project_id, store=store)
    try:
        return await asyncio.to_thread(api_get_binding, tenant, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
