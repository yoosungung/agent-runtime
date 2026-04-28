"""Admin router for custom image mode pool lifecycle.

POST   /api/admin/custom-images                      — register + deploy
GET    /api/admin/custom-images                      — list all image-mode entries
DELETE /api/admin/custom-images/{kind}/{slug}        — retire + teardown
PATCH  /api/admin/custom-images/{kind}/{slug}        — update operational params
POST   /api/admin/custom-images/{kind}/{slug}/restart — rolling restart
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.audit import log_event, make_audit_row
from backend.deps import check_csrf, get_db, get_settings, require_admin
from backend.settings import Settings
from runtime_common.db.models import SourceMetaRow
from runtime_common.schemas import parse_runtime_pool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/custom-images",
    tags=["custom-images"],
    dependencies=[Depends(require_admin), Depends(check_csrf)],
)

_RE_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_RE_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_MERGED_CONFIG_BYTES = 16 * 1024  # 16KB


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Convert arbitrary text to a lowercase, hyphen-separated slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:45]


def _derive_slug(name: str, version: str) -> str:
    """Auto-derive slug from name + version. Max 45 chars total."""
    n = _slugify(name)
    v = _slugify(version)
    combined = f"{n}-{v}"
    if len(combined) > 45:
        combined = combined[:45].rstrip("-")
    # Ensure starts and ends with alnum
    combined = re.sub(r"^[^a-z0-9]+", "", combined)
    combined = re.sub(r"[^a-z0-9]+$", "", combined)
    return combined or "custom"


def _validate_slug(slug: str) -> None:
    if not _RE_SLUG.match(slug) or len(slug) > 45:
        raise HTTPException(
            status_code=400,
            detail="slug must match [a-z0-9]([a-z0-9-]*[a-z0-9])? and be ≤ 45 chars",
        )


def _validate_config(config: dict) -> None:
    if len(json.dumps(config).encode()) > _MAX_MERGED_CONFIG_BYTES:
        raise HTTPException(
            status_code=413,
            detail="config exceeds 16KB limit (must fit in Envoy x-runtime-cfg header)",
        )


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CustomImageCreateRequest(BaseModel):
    kind: str = Field(..., description="'agent' | 'mcp'")
    name: str = Field(..., description="Logical name")
    version: str = Field(..., description="Version string")
    image_uri: str = Field(..., description="OCI image URI")
    image_digest: str | None = Field(default=None, description="sha256:... digest")
    slug: str | None = Field(default=None, description="Override auto-derived slug")
    replicas_max: int = Field(default=5, ge=1, le=100)
    resources: dict | None = Field(default=None, description="K8s resource requests/limits")
    image_pull_secret: str | None = None
    env: dict[str, str] | None = None
    config: dict = Field(default_factory=dict, description="Source-level default config")


class CustomImagePatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    replicas_max: int | None = Field(default=None, ge=1, le=100)
    resources: dict | None = None
    env: dict[str, str] | None = None
    config: dict | None = None


class CustomImageResponse(BaseModel):
    id: int
    kind: str
    name: str
    version: str
    slug: str
    runtime_pool: str
    image_uri: str | None
    image_digest: str | None
    config: dict
    status: str
    deploy_mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


def _row_to_response(row: SourceMetaRow) -> CustomImageResponse:
    return CustomImageResponse.model_validate(row)


# ---------------------------------------------------------------------------
# GET /api/admin/custom-images
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CustomImageResponse])
async def list_custom_images(
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[CustomImageResponse]:
    stmt = select(SourceMetaRow).where(SourceMetaRow.deploy_mode == "image")
    if kind:
        if kind not in ("agent", "mcp"):
            raise HTTPException(status_code=400, detail="kind must be 'agent' or 'mcp'")
        stmt = stmt.where(SourceMetaRow.kind == kind)
    stmt = stmt.order_by(SourceMetaRow.created_at.desc())
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/admin/custom-images
# ---------------------------------------------------------------------------


@router.post("", response_model=CustomImageResponse, status_code=201)
async def create_custom_image(
    request: Request,
    body: CustomImageCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal=Depends(require_admin),
) -> CustomImageResponse:
    if body.kind not in ("agent", "mcp"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'mcp'")

    if body.image_digest and not _RE_IMAGE_DIGEST.match(body.image_digest):
        raise HTTPException(status_code=400, detail="image_digest must match sha256:[0-9a-f]{64}")

    _validate_config(body.config)

    # Derive or validate slug
    slug = body.slug or _derive_slug(body.name, body.version)
    _validate_slug(slug)

    runtime_pool = f"{body.kind}:custom:{slug}"

    # Verify parse_runtime_pool accepts it
    try:
        parse_runtime_pool(runtime_pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    deploy_api_url = settings.DEPLOY_API_URL

    # Step (a): validate; step (b): INSERT with status='pending'
    row = SourceMetaRow(
        kind=body.kind,
        name=body.name,
        version=body.version,
        runtime_pool=runtime_pool,
        entrypoint=None,
        bundle_uri=None,
        checksum=None,
        sig_uri=None,
        config=body.config,
        retired=False,
        deploy_mode="image",
        image_uri=body.image_uri,
        image_digest=body.image_digest,
        slug=slug,
        status="pending",
    )
    db.add(row)
    db.add(
        make_audit_row(
            "custom_image.create",
            principal.user_id,
            principal.sub,
            kind=body.kind,
            name=body.name,
            version=body.version,
            slug=slug,
        )
    )
    try:
        await db.flush()
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        msg = str(exc.orig) if exc.orig else str(exc)
        if "uq_source_meta_kind_slug" in msg or "uq_source_meta_nv" in msg:
            raise HTTPException(
                status_code=409,
                detail=f"custom image (kind={body.kind}, name={body.name}, version={body.version}) or slug '{slug}' already exists",
            ) from exc
        raise HTTPException(status_code=409, detail="conflict") from exc

    # Step (c): create K8s resources
    k8s: Any = getattr(request.app.state, "k8s_pool_manager", None)
    if k8s is None:
        # K8s not configured (e.g. local dev) — mark active immediately
        row.status = "active"
        await db.commit()
        await db.refresh(row)
        logger.warning("custom_image.k8s_skipped (no k8s_pool_manager)", extra={"slug": slug})
        return _row_to_response(row)

    try:
        await k8s.create_pool(
            kind=body.kind,
            slug=slug,
            image_uri=body.image_uri,
            image_digest=body.image_digest,
            replicas_max=body.replicas_max,
            resources=body.resources,
            image_pull_secret=body.image_pull_secret,
            env_vars=body.env,
            deploy_api_url=deploy_api_url,
        )
    except Exception as exc:
        logger.error("custom_image.k8s_create_failed", extra={"slug": slug, "error": str(exc)})
        row.status = "failed"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"K8s create failed: {exc}") from exc

    # Step (d): wait for ready
    timeout = settings.K8S_DEPLOY_READY_TIMEOUT_SEC
    ready = await k8s.wait_ready(body.kind, slug, timeout_sec=timeout)

    if not ready:
        logger.error("custom_image.k8s_not_ready", extra={"slug": slug})
        row.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=504,
            detail=f"Deployment not ready within {timeout}s. Check K8s events.",
        )

    # Step (e): mark active
    row.status = "active"
    await db.commit()
    await db.refresh(row)

    log_event(
        "custom_image.active",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=row.id,
        slug=slug,
        runtime_pool=runtime_pool,
    )
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# DELETE /api/admin/custom-images/{kind}/{slug}
# ---------------------------------------------------------------------------


@router.delete("/{kind}/{slug}", status_code=204)
async def delete_custom_image(
    kind: str,
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal=Depends(require_admin),
) -> None:
    if kind not in ("agent", "mcp"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'mcp'")

    stmt = select(SourceMetaRow).where(
        SourceMetaRow.kind == kind,
        SourceMetaRow.slug == slug,
        SourceMetaRow.deploy_mode == "image",
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"custom image {kind}/{slug} not found")

    row.status = "retired"
    row.retired = True
    db.add(
        make_audit_row(
            "custom_image.delete",
            principal.user_id,
            principal.sub,
            kind=kind,
            slug=slug,
            id=row.id,
        )
    )
    await db.commit()

    # Tear down K8s resources
    k8s: Any = getattr(request.app.state, "k8s_pool_manager", None)
    if k8s is not None:
        await k8s.delete_pool(kind, slug)

    log_event(
        "custom_image.delete",
        actor_id=principal.user_id,
        actor=principal.sub,
        id=row.id,
        slug=slug,
    )


# ---------------------------------------------------------------------------
# PATCH /api/admin/custom-images/{kind}/{slug}
# ---------------------------------------------------------------------------


@router.patch("/{kind}/{slug}", response_model=CustomImageResponse)
async def patch_custom_image(
    kind: str,
    slug: str,
    body: CustomImagePatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal=Depends(require_admin),
) -> CustomImageResponse:
    if kind not in ("agent", "mcp"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'mcp'")

    stmt = select(SourceMetaRow).where(
        SourceMetaRow.kind == kind,
        SourceMetaRow.slug == slug,
        SourceMetaRow.deploy_mode == "image",
        SourceMetaRow.status == "active",
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"active custom image {kind}/{slug} not found"
        )

    if body.config is not None:
        _validate_config(body.config)
        row.config = body.config

    db.add(
        make_audit_row(
            "custom_image.patch",
            principal.user_id,
            principal.sub,
            kind=kind,
            slug=slug,
            changed_fields=list(body.model_dump(exclude_none=True).keys()),
        )
    )
    await db.commit()
    await db.refresh(row)

    # Apply K8s changes
    k8s: Any = getattr(request.app.state, "k8s_pool_manager", None)
    if k8s is not None and (body.replicas_max or body.resources or body.env):
        try:
            await k8s.patch_deployment(
                kind=kind,
                slug=slug,
                replicas_max=body.replicas_max,
                resources=body.resources,
                env_vars=body.env,
            )
        except Exception as exc:
            logger.error(
                "custom_image.k8s_patch_failed",
                extra={"slug": slug, "error": str(exc)},
            )

    log_event(
        "custom_image.patch",
        actor_id=principal.user_id,
        actor=principal.sub,
        slug=slug,
    )
    return _row_to_response(row)


# ---------------------------------------------------------------------------
# POST /api/admin/custom-images/{kind}/{slug}/restart
# ---------------------------------------------------------------------------


@router.post("/{kind}/{slug}/restart", status_code=204)
async def restart_custom_image(
    kind: str,
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal=Depends(require_admin),
) -> None:
    if kind not in ("agent", "mcp"):
        raise HTTPException(status_code=400, detail="kind must be 'agent' or 'mcp'")

    stmt = select(SourceMetaRow).where(
        SourceMetaRow.kind == kind,
        SourceMetaRow.slug == slug,
        SourceMetaRow.deploy_mode == "image",
        SourceMetaRow.status == "active",
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"active custom image {kind}/{slug} not found"
        )

    k8s: Any = getattr(request.app.state, "k8s_pool_manager", None)
    if k8s is None:
        raise HTTPException(status_code=503, detail="K8s not configured")

    try:
        await k8s.restart_pool(kind, slug)
    except Exception as exc:
        logger.error("custom_image.k8s_restart_failed", extra={"slug": slug, "error": str(exc)})
        raise HTTPException(status_code=500, detail=f"K8s restart failed: {exc}") from exc

    db.add(
        make_audit_row(
            "custom_image.restart",
            principal.user_id,
            principal.sub,
            kind=kind,
            slug=slug,
        )
    )
    await db.commit()

    log_event(
        "custom_image.restart",
        actor_id=principal.user_id,
        actor=principal.sub,
        slug=slug,
    )
