from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import make_audit_row
from backend.deps import check_csrf, get_db, get_principal, require_admin
from backend.infra_reconciler import reconcile_infra
from runtime_common.db.models import InfraMetaRow
from runtime_common.infra_env import (
    merge_infra_env,
    normalize_stored_env,
    validate_infra_env_patch,
    validate_infra_secret_keys,
    validate_infra_secrets_input,
)
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/infra-meta",
    tags=["infra-meta"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

MAX_ENV_BYTES = 16 * 1024
_GLOBAL_SCOPE = "global"
_GLOBAL_SCOPE_KEY = ""


class InfraMetaResponse(BaseModel):
    scope: str
    scope_key: str
    env: dict
    secret_keys: list[str]
    updated_at: datetime | None
    reconciled: bool = True

    model_config = {"from_attributes": True}


class InfraMetaUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    env: dict | None = None
    secrets: dict[str, str] | None = None


def _row_to_response(
    row: InfraMetaRow,
    *,
    reconciled: bool = True,
    env: dict | None = None,
) -> InfraMetaResponse:
    keys = row.secret_keys if isinstance(row.secret_keys, list) else []
    return InfraMetaResponse(
        scope=row.scope,
        scope_key=row.scope_key,
        env=env if env is not None else row.env,
        secret_keys=[str(k) for k in keys],
        updated_at=row.updated_at,
        reconciled=reconciled,
    )


def _validate_env_size(env: dict) -> None:
    if len(json.dumps(env).encode()) > MAX_ENV_BYTES:
        raise HTTPException(status_code=413, detail="env exceeds 16KB limit")


@router.get("", response_model=InfraMetaResponse)
async def get_infra_meta(db: AsyncSession = Depends(get_db)) -> InfraMetaResponse:
    result = await db.execute(
        select(InfraMetaRow).where(
            InfraMetaRow.scope == _GLOBAL_SCOPE,
            InfraMetaRow.scope_key == _GLOBAL_SCOPE_KEY,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return InfraMetaResponse(
            scope=_GLOBAL_SCOPE,
            scope_key=_GLOBAL_SCOPE_KEY,
            env={},
            secret_keys=[],
            updated_at=None,
            reconciled=True,
        )
    normalized_env = normalize_stored_env(row.env if isinstance(row.env, dict) else {})
    return _row_to_response(row, env=normalized_env)


@router.put("", response_model=InfraMetaResponse)
async def upsert_infra_meta(
    body: InfraMetaUpsertRequest,
    request: Request,
    principal: Principal = Depends(get_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db),
) -> InfraMetaResponse:
    if body.env is None and body.secrets is None:
        raise HTTPException(status_code=400, detail="at least one of env or secrets is required")

    validated_secrets: dict[str, str] | None = None
    if body.secrets is not None:
        try:
            validated_secrets = validate_infra_secrets_input(body.secrets)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await db.execute(
        select(InfraMetaRow).where(
            InfraMetaRow.scope == _GLOBAL_SCOPE,
            InfraMetaRow.scope_key == _GLOBAL_SCOPE_KEY,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = InfraMetaRow(scope=_GLOBAL_SCOPE, scope_key=_GLOBAL_SCOPE_KEY)
        db.add(row)

    if body.env is not None:
        try:
            patch = validate_infra_env_patch(body.env)
            base = normalize_stored_env(row.env if isinstance(row.env, dict) else {})
            row.env = merge_infra_env(base, patch)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _validate_env_size(row.env)

    if validated_secrets is not None:
        existing_keys = row.secret_keys if isinstance(row.secret_keys, list) else []
        try:
            merged_keys = validate_infra_secret_keys(
                [str(k) for k in existing_keys] + list(validated_secrets.keys())
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.secret_keys = merged_keys

    row.updated_at = datetime.now(UTC)
    db.add(
        make_audit_row(
            "infra_meta.upsert",
            principal.user_id,
            principal.sub,
            env_keys=sorted(row.env.keys()) if body.env is not None else None,
            secret_keys=row.secret_keys if validated_secrets is not None else None,
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(row)

    k8s = getattr(request.app.state, "k8s_pool_manager", None)
    reconciled = True
    if k8s is not None:
        try:
            await reconcile_infra(
                k8s,
                env=row.env,
                secrets_patch=validated_secrets,
            )
        except Exception as exc:
            logger.error("infra_meta.reconcile_failed", extra={"error": str(exc)})
            reconciled = False
    else:
        logger.warning("infra_meta.k8s_skipped (no k8s_pool_manager)")
        reconciled = False

    if not reconciled:
        return _row_to_response(row, reconciled=False)

    return _row_to_response(row)
