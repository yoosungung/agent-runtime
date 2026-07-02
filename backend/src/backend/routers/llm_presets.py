from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import make_audit_row
from backend.deps import check_csrf, get_db, get_principal, require_admin
from backend.infra_reconciler import reconcile_infra
from runtime_common.db.models import LlmPresetRow
from runtime_common.schemas import Principal

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/llm-presets",
    tags=["llm-presets"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

PRESET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class LlmPresetResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    mode: str
    frontier_provider: str | None = None
    model_id: str
    openai_api_base: str | None = None
    slm_runtime: str | None = None
    is_default: bool
    api_key_configured: bool
    context_window_tokens: int
    max_output_tokens: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LlmPresetCreateRequest(BaseModel):
    name: str
    description: str | None = None
    mode: str
    frontier_provider: str | None = None
    model_id: str
    openai_api_base: str | None = None
    slm_runtime: str | None = None
    is_default: bool = False
    api_key: str | None = None
    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not PRESET_NAME_RE.match(v):
            raise ValueError("Preset name must match [A-Z][A-Z0-9_]*")
        return v

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("frontier", "openai_compatible"):
            raise ValueError("mode must be 'frontier' or 'openai_compatible'")
        return v


class LlmPresetUpdateRequest(BaseModel):
    description: str | None = None
    mode: str
    frontier_provider: str | None = None
    model_id: str
    openai_api_base: str | None = None
    slm_runtime: str | None = None
    is_default: bool = False
    api_key: str | None = None
    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("frontier", "openai_compatible"):
            raise ValueError("mode must be 'frontier' or 'openai_compatible'")
        return v


@router.get("", response_model=list[LlmPresetResponse])
async def list_llm_presets(db: AsyncSession = Depends(get_db)) -> list[LlmPresetResponse]:
    result = await db.execute(select(LlmPresetRow).order_by(LlmPresetRow.name))
    rows = result.scalars().all()
    return [LlmPresetResponse.model_validate(row) for row in rows]


@router.post("", response_model=LlmPresetResponse)
async def create_llm_preset(
    body: LlmPresetCreateRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> LlmPresetResponse:
    # Check duplication
    dup_res = await db.execute(select(LlmPresetRow).where(LlmPresetRow.name == body.name))
    if dup_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Preset name {body.name!r} already exists")

    if body.is_default:
        # Reset other default preset
        await db.execute(update(LlmPresetRow).values(is_default=False))

    row = LlmPresetRow(
        name=body.name,
        description=body.description,
        mode=body.mode,
        frontier_provider=body.frontier_provider,
        model_id=body.model_id,
        openai_api_base=body.openai_api_base,
        slm_runtime=body.slm_runtime,
        is_default=body.is_default,
        api_key_configured=bool(body.api_key),
        context_window_tokens=body.context_window_tokens,
        max_output_tokens=body.max_output_tokens,
    )
    db.add(row)
    
    db.add(
        make_audit_row(
            "llm_preset.create",
            principal.user_id,
            principal.sub,
            preset_name=body.name,
            is_default=body.is_default,
        )
    )
    await db.flush()

    # Reconcile K8s infra
    k8s = getattr(request.app.state, "k8s_pool_manager", None)
    reconciled = True
    secrets_patch = {}
    if body.api_key:
        secrets_patch[f"LLM_PRESET_{body.name}_API_KEY"] = body.api_key.strip()

    if k8s is not None:
        try:
            await reconcile_infra(
                k8s,
                db,
                secrets_patch=secrets_patch if secrets_patch else None,
            )
        except Exception as exc:
            logger.error("llm_preset.reconcile_failed", extra={"error": str(exc)})
            reconciled = False

    await db.commit()
    await db.refresh(row)

    return LlmPresetResponse.model_validate(row)


@router.get("/{preset_id}", response_model=LlmPresetResponse)
async def get_llm_preset(preset_id: int, db: AsyncSession = Depends(get_db)) -> LlmPresetResponse:
    row = await db.get(LlmPresetRow, preset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    return LlmPresetResponse.model_validate(row)


@router.put("/{preset_id}", response_model=LlmPresetResponse)
async def update_llm_preset(
    preset_id: int,
    body: LlmPresetUpdateRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> LlmPresetResponse:
    row = await db.get(LlmPresetRow, preset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Preset not found")

    if body.is_default and not row.is_default:
        # Reset other default preset
        await db.execute(update(LlmPresetRow).values(is_default=False))

    row.description = body.description
    row.mode = body.mode
    row.frontier_provider = body.frontier_provider
    row.model_id = body.model_id
    row.openai_api_base = body.openai_api_base
    row.slm_runtime = body.slm_runtime
    row.is_default = body.is_default
    row.context_window_tokens = body.context_window_tokens
    row.max_output_tokens = body.max_output_tokens
    if body.api_key is not None:
        row.api_key_configured = bool(body.api_key)
    row.updated_at = datetime.now(UTC)

    db.add(row)
    db.add(
        make_audit_row(
            "llm_preset.update",
            principal.user_id,
            principal.sub,
            preset_name=row.name,
            is_default=body.is_default,
        )
    )
    await db.flush()

    # Reconcile K8s infra
    k8s = getattr(request.app.state, "k8s_pool_manager", None)
    reconciled = True
    secrets_patch = {}
    if body.api_key is not None and body.api_key.strip():
        secrets_patch[f"LLM_PRESET_{row.name}_API_KEY"] = body.api_key.strip()

    if k8s is not None:
        try:
            await reconcile_infra(
                k8s,
                db,
                secrets_patch=secrets_patch if secrets_patch else None,
            )
        except Exception as exc:
            logger.error("llm_preset.reconcile_failed", extra={"error": str(exc)})
            reconciled = False

    await db.commit()
    await db.refresh(row)
    return LlmPresetResponse.model_validate(row)


@router.delete("/{preset_id}")
async def delete_llm_preset(
    preset_id: int,
    request: Request,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    row = await db.get(LlmPresetRow, preset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Preset not found")

    preset_name = row.name
    await db.delete(row)
    db.add(
        make_audit_row(
            "llm_preset.delete",
            principal.user_id,
            principal.sub,
            preset_name=preset_name,
        )
    )
    await db.flush()

    # Reconcile K8s infra
    k8s = getattr(request.app.state, "k8s_pool_manager", None)
    reconciled = True
    secrets_delete = [f"LLM_PRESET_{preset_name}_API_KEY"]

    if k8s is not None:
        try:
            await reconcile_infra(
                k8s,
                db,
                secrets_delete=secrets_delete,
            )
        except Exception as exc:
            logger.error("llm_preset.reconcile_failed", extra={"error": str(exc)})
            reconciled = False

    await db.commit()
    return {"status": "ok"}
