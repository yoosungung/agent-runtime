"""Pipeline knowledge project validation for general agents and MCP policy."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from runtime_common.db.models import SourceMetaRow
from runtime_common.knowledge import mcp_requires_knowledge_project


async def _latest_mcp_source_meta(db: AsyncSession, name: str) -> SourceMetaRow | None:
    result = await db.execute(
        select(SourceMetaRow)
        .where(
            SourceMetaRow.kind == "mcp",
            SourceMetaRow.name == name,
            SourceMetaRow.retired.is_(False),
        )
        .order_by(SourceMetaRow.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def mcp_servers_requiring_knowledge(
    db: AsyncSession,
    mcp_servers: list[str],
) -> list[str]:
    """Return MCP server names that declare config.knowledge.requires_project."""
    required: list[str] = []
    for server in mcp_servers:
        row = await _latest_mcp_source_meta(db, server)
        if row is not None and mcp_requires_knowledge_project(row.config):
            required.append(server)
    return required


async def validate_knowledge_projects(
    db: AsyncSession,
    *,
    tenant: str | None,
    project_ids: list[str],
    mcp_servers: list[str],
    project_store,
) -> list[str]:
    """Validate project ownership and conditional requirement. Returns required MCP names."""
    if not tenant:
        if project_ids:
            raise HTTPException(status_code=403, detail="tenant required for knowledge projects")
        required = await mcp_servers_requiring_knowledge(db, mcp_servers)
        if required:
            raise HTTPException(
                status_code=400,
                detail=(
                    "knowledge_project_ids required for MCP servers: "
                    + ", ".join(sorted(required))
                ),
            )
        return required

    deduped = list(dict.fromkeys(project_ids))
    for project_id in deduped:
        project = await asyncio.to_thread(project_store.get_project, tenant, project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail=f"pipeline project not found: {project_id}",
            )

    required = await mcp_servers_requiring_knowledge(db, mcp_servers)
    if required and not deduped:
        raise HTTPException(
            status_code=400,
            detail=(
                "knowledge_project_ids required for MCP servers: "
                + ", ".join(sorted(required))
            ),
        )
    return required
