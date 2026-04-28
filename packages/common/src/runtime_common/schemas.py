from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from runtime_common.db.models import SourceMetaRow, UserMetaRow


class AgentRuntimeKind(StrEnum):
    COMPILED_GRAPH = "compiled_graph"
    ADK = "adk"
    CUSTOM = "custom"  # image-mode marker — not used in bundle pool routing


class McpRuntimeKind(StrEnum):
    FASTMCP = "fastmcp"
    MCP_SDK = "mcp_sdk"
    CUSTOM = "custom"  # image-mode marker — not used in bundle pool routing


# ---------------------------------------------------------------------------
# runtime_pool identifier helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True)
class RuntimePoolId:
    """Parsed runtime_pool identifier.

    Bundle mode:  kind='agent', runtime_kind='compiled_graph', slug=None
    Image mode:   kind='agent', runtime_kind='custom', slug='summarizer-v1'
    """

    kind: str
    runtime_kind: str
    slug: str | None = None

    @property
    def is_image_mode(self) -> bool:
        return self.slug is not None

    def __str__(self) -> str:
        if self.slug:
            return f"{self.kind}:{self.runtime_kind}:{self.slug}"
        return f"{self.kind}:{self.runtime_kind}"


def parse_runtime_pool(runtime_pool: str) -> RuntimePoolId:
    """Parse a runtime_pool string into a RuntimePoolId.

    Valid formats:
      '{kind}:{runtime_kind}'            → bundle mode (slug=None)
      '{kind}:custom:{slug}'             → image mode
    """
    parts = runtime_pool.split(":", 2)
    if len(parts) == 2:
        kind, runtime_kind = parts
        return RuntimePoolId(kind=kind, runtime_kind=runtime_kind, slug=None)
    if len(parts) == 3:
        kind, runtime_kind, slug = parts
        if runtime_kind != "custom":
            raise ValueError(
                f"three-part runtime_pool must use 'custom' as runtime_kind, got {runtime_kind!r}"
            )
        if not _SLUG_RE.match(slug) or len(slug) > 45:
            raise ValueError(
                f"slug must match [a-z0-9]([a-z0-9-]*[a-z0-9])? and be ≤ 45 chars, got {slug!r}"
            )
        return RuntimePoolId(kind=kind, runtime_kind=runtime_kind, slug=slug)
    raise ValueError(f"invalid runtime_pool format: {runtime_pool!r}")


def image_mode_service_name(pool_id: RuntimePoolId) -> str:
    """Derive K8s Service name for an image-mode pool: '{kind}-pool-custom-{slug}'."""
    if not pool_id.is_image_mode:
        raise ValueError("image_mode_service_name requires an image-mode RuntimePoolId")
    return f"{pool_id.kind}-pool-custom-{pool_id.slug}"


class ResourceRef(BaseModel):
    kind: str  # 'agent' | 'mcp'
    name: str


class SourceMeta(BaseModel):
    """Registered deployable unit. Written by deploy-api, read by gateways and base-image loaders."""  # noqa: E501

    id: int | None = Field(
        default=None, description="DB row id (set by deploy-api; ignored by runtime)"
    )
    kind: str = Field(default="agent", description="'agent' | 'mcp'")
    name: str = Field(..., description="Logical name, e.g. 'support-agent'")
    version: str = Field(..., description="Semver or git sha")
    runtime_pool: str = Field(..., description="Pool identifier, e.g. 'agent:compiled_graph'")
    entrypoint: str | None = Field(
        default=None, description="Python path, e.g. 'pkg.mod:factory'. None for image mode."
    )
    bundle_uri: str | None = Field(
        default=None, description="s3://... or file://... location of code bundle. None for image mode."
    )
    checksum: str | None = None
    sig_uri: str | None = None
    config: dict = Field(
        default_factory=dict,
        description="Bundle-default config. Runtime merges with user_meta.config (user wins).",
    )
    # Image mode fields
    deploy_mode: str = Field(default="bundle", description="'bundle' | 'image'")
    image_uri: str | None = Field(default=None, description="OCI image URI for image mode")
    image_digest: str | None = Field(default=None, description="OCI image digest for image mode")
    slug: str | None = Field(default=None, description="URL-safe slug for image mode, e.g. 'summarizer-v1'")
    status: str = Field(default="active", description="'pending' | 'active' | 'failed' | 'retired'")
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: SourceMetaRow) -> SourceMeta:
        """Convert a ``SourceMetaRow`` ORM instance to a ``SourceMeta`` pydantic model."""
        return cls(
            id=row.id,
            kind=row.kind,
            name=row.name,
            version=row.version,
            runtime_pool=row.runtime_pool,
            entrypoint=row.entrypoint,
            bundle_uri=row.bundle_uri,
            checksum=row.checksum,
            sig_uri=row.sig_uri,
            config=row.config,
            deploy_mode=row.deploy_mode,
            image_uri=row.image_uri,
            image_digest=row.image_digest,
            slug=row.slug,
            status=row.status,
            created_at=row.created_at,
        )


class UserMeta(BaseModel):
    """Per-user mutable metadata. Mutable; fetched fresh on every invoke."""

    principal_id: str
    config: dict = Field(default_factory=dict)
    secrets_ref: str | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: UserMetaRow) -> UserMeta:
        """Convert a ``UserMetaRow`` ORM instance to a ``UserMeta`` pydantic model."""
        return cls(
            principal_id=row.principal_id,
            config=row.config,
            secrets_ref=row.secrets_ref,
            updated_at=row.updated_at,
        )


class ResolveResponse(BaseModel):
    source: SourceMeta
    user: UserMeta | None = None


class Principal(BaseModel):
    """Authenticated caller identity returned by auth service."""

    sub: str
    user_id: int = 0
    tenant: str | None = None
    access: list[ResourceRef] = Field(default_factory=list)
    grace_applied: bool = False
    is_admin: bool = False
    must_change_password: bool = False

    def can_access(self, kind: str, name: str) -> bool:
        return any(r.kind == kind and r.name == name for r in self.access)


class AgentInvokeRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict[str, object]
    session_id: str | None = None
    principal: Principal | None = None
    stream: bool = False


class McpInvokeRequest(BaseModel):
    server: str
    version: str | None = None
    tool: str
    arguments: dict[str, object]
    principal: Principal | None = None
