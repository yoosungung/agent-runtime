"""Shared helpers for resource access policy (visibility + ACL)."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from runtime_common.db.models import SourceMetaRow
from runtime_common.general_visibility import GeneralVisibility


async def resolve_latest_resource_visibility(
    db: AsyncSession,
    kind: str,
    name: str,
) -> str | None:
    result = await db.execute(
        select(SourceMetaRow.visibility)
        .where(
            SourceMetaRow.kind == kind,
            SourceMetaRow.name == name,
            SourceMetaRow.retired.is_(False),
        )
        .order_by(SourceMetaRow.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def require_allowlist_visibility(
    db: AsyncSession,
    kind: str,
    name: str,
) -> None:
    visibility = await resolve_latest_resource_visibility(db, kind, name)
    if visibility is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active source_meta found with kind={kind}, name={name}",
        )
    if visibility != GeneralVisibility.ALLOWLIST:
        raise HTTPException(
            status_code=400,
            detail="User grants apply only when resource visibility is allowlist",
        )
