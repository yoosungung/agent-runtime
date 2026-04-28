from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from runtime_common.db.models import SourceMetaRow, UserMetaRow


class AgentRuntimeKind(StrEnum):
    COMPILED_GRAPH = "compiled_graph"
    ADK = "adk"
    CUSTOM = "custom"


class McpRuntimeKind(StrEnum):
    FASTMCP = "fastmcp"
    MCP_SDK = "mcp_sdk"
    CUSTOM = "custom"


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
    entrypoint: str = Field(..., description="Python path, e.g. 'pkg.mod:factory'")
    bundle_uri: str = Field(..., description="s3://... or file://... location of code bundle")
    checksum: str | None = None
    sig_uri: str | None = None
    config: dict = Field(
        default_factory=dict,
        description="Bundle-default config. Runtime merges with user_meta.config (user wins).",
    )
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
