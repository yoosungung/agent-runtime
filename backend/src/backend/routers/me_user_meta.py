from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import check_csrf, get_db, get_principal
from runtime_common.config_schema import UserConfig, UserMetaFormTemplate, is_user_meta_required, validate_template_required_fields
from runtime_common.db.models import SourceMetaRow, UserMetaRow
from runtime_common.knowledge import mcp_requires_knowledge_project
from runtime_common.schemas import Principal, ResourceRef

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/me",
    tags=["me-user-meta"],
    dependencies=[Depends(get_principal), Depends(check_csrf)],
)

RE_SECRETS_REF = re.compile(r"^(vault|env|aws-sm)://.+$")
MAX_CONFIG_BYTES = 64 * 1024


class AccessResourceResponse(BaseModel):
    kind: str
    name: str
    version: str
    source_meta_id: int
    runtime_pool: str
    has_user_meta: bool
    user_meta_required: bool = True
    requires_knowledge_project: bool = False
    template_description: str | None = None
    template_field_count: int = 0


class AccessResourceListResponse(BaseModel):
    items: list[AccessResourceResponse]
    total: int


class MeUserMetaResponse(BaseModel):
    kind: str
    name: str
    version: str
    source_meta_id: int
    source_config: dict
    user_meta_template: dict
    config: dict
    secrets_ref: str | None
    updated_at: datetime | None = None


class MeUserMetaUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    name: str
    config: dict | None = None
    secrets_ref: str | None = None


def _assert_can_access(principal: Principal, kind: str, name: str) -> None:
    if not principal.can_access(kind, name):
        raise HTTPException(status_code=403, detail="No access to this resource")


def _validate_secrets_ref(secrets_ref: str | None) -> None:
    if secrets_ref is not None and not RE_SECRETS_REF.match(secrets_ref):
        raise HTTPException(
            status_code=400,
            detail="secrets_ref must match ^(vault|env|aws-sm)://.+$",
        )


def _validate_config(config: dict | None) -> dict:
    if config is None:
        return {}
    import json

    serialized = json.dumps(config)
    if len(serialized.encode()) > MAX_CONFIG_BYTES:
        raise HTTPException(status_code=413, detail="config exceeds 64KB limit")
    validated = UserConfig.model_validate(config)
    return validated.model_dump(mode="json", exclude_none=True)


async def _resolve_latest_source_meta(
    db: AsyncSession,
    kind: str,
    name: str,
) -> SourceMetaRow:
    stmt = (
        select(SourceMetaRow)
        .where(
            SourceMetaRow.kind == kind,
            SourceMetaRow.name == name,
            SourceMetaRow.retired == False,  # noqa: E712
            SourceMetaRow.status != "pending",
        )
        .order_by(SourceMetaRow.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="source_meta not found")
    return row


def _template_summary(template_dict: dict) -> tuple[bool, str | None, int]:
    try:
        template = UserMetaFormTemplate.model_validate(template_dict)
    except Exception:
        return True, None, 0
    return (
        is_user_meta_required(template),
        template.description,
        len(template.fields),
    )


def _access_resources_for_kind(principal: Principal, kind: str) -> list[ResourceRef]:
    return [ref for ref in principal.access if ref.kind == kind]


@router.get("/access-resources", response_model=AccessResourceListResponse)
async def list_access_resources(
    kind: str = Query(..., pattern="^(agent|mcp)$"),
    surface: str | None = Query(None, pattern="^(chat|all)$"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> AccessResourceListResponse:
    refs = _access_resources_for_kind(principal, kind)
    items: list[AccessResourceResponse] = []

    for ref in refs:
        try:
            source = await _resolve_latest_source_meta(db, ref.kind, ref.name)
        except HTTPException:
            continue

        if kind == "agent" and surface == "chat" and not source.chat_selectable:
            continue

        um_result = await db.execute(
            select(UserMetaRow).where(
                UserMetaRow.source_meta_id == source.id,
                UserMetaRow.principal_id == principal.sub,
            )
        )
        has_user_meta = um_result.scalar_one_or_none() is not None
        user_meta_required, desc, field_count = _template_summary(source.user_meta_template)

        items.append(
            AccessResourceResponse(
                kind=source.kind,
                name=source.name,
                version=source.version,
                source_meta_id=source.id,
                runtime_pool=source.runtime_pool,
                has_user_meta=has_user_meta,
                user_meta_required=user_meta_required,
                requires_knowledge_project=mcp_requires_knowledge_project(source.config),
                template_description=desc,
                template_field_count=field_count,
            )
        )

    items.sort(key=lambda item: item.name)
    return AccessResourceListResponse(items=items, total=len(items))


@router.get("/user-meta", response_model=MeUserMetaResponse)
async def get_my_user_meta(
    kind: str = Query(..., pattern="^(agent|mcp)$"),
    name: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MeUserMetaResponse:
    _assert_can_access(principal, kind, name)
    source = await _resolve_latest_source_meta(db, kind, name)

    um_result = await db.execute(
        select(UserMetaRow).where(
            UserMetaRow.source_meta_id == source.id,
            UserMetaRow.principal_id == principal.sub,
        )
    )
    um_row = um_result.scalar_one_or_none()

    return MeUserMetaResponse(
        kind=source.kind,
        name=source.name,
        version=source.version,
        source_meta_id=source.id,
        source_config=source.config,
        user_meta_template=source.user_meta_template,
        config=um_row.config if um_row else {},
        secrets_ref=um_row.secrets_ref if um_row else None,
        updated_at=um_row.updated_at if um_row else None,
    )


@router.put("/user-meta", response_model=MeUserMetaResponse)
async def upsert_my_user_meta(
    body: MeUserMetaUpsertRequest,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> MeUserMetaResponse:
    _assert_can_access(principal, body.kind, body.name)
    source = await _resolve_latest_source_meta(db, body.kind, body.name)

    config = _validate_config(body.config)
    _validate_secrets_ref(body.secrets_ref)

    try:
        template = UserMetaFormTemplate.model_validate(source.user_meta_template)
        if not is_user_meta_required(template):
            raise HTTPException(
                status_code=400,
                detail="User meta is not required for this resource",
            )
        validate_template_required_fields(template, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing_result = await db.execute(
        select(UserMetaRow).where(
            UserMetaRow.source_meta_id == source.id,
            UserMetaRow.principal_id == principal.sub,
        )
    )
    row = existing_result.scalar_one_or_none()

    if row is None:
        row = UserMetaRow(
            source_meta_id=source.id,
            principal_id=principal.sub,
            config=config,
            secrets_ref=body.secrets_ref,
        )
        db.add(row)
    else:
        if body.config is not None:
            row.config = config
        if body.secrets_ref is not None:
            row.secrets_ref = body.secrets_ref
        row.updated_at = datetime.now(UTC)

    await db.flush()
    await db.commit()
    await db.refresh(row)

    return MeUserMetaResponse(
        kind=source.kind,
        name=source.name,
        version=source.version,
        source_meta_id=source.id,
        source_config=source.config,
        user_meta_template=source.user_meta_template,
        config=row.config,
        secrets_ref=row.secrets_ref,
        updated_at=row.updated_at,
    )


@router.delete("/user-meta", status_code=204)
async def delete_my_user_meta(
    kind: str = Query(..., pattern="^(agent|mcp)$"),
    name: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> None:
    _assert_can_access(principal, kind, name)
    source = await _resolve_latest_source_meta(db, kind, name)

    result = await db.execute(
        select(UserMetaRow).where(
            UserMetaRow.source_meta_id == source.id,
            UserMetaRow.principal_id == principal.sub,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="user_meta not found")
    await db.delete(row)
    await db.commit()
