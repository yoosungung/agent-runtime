from __future__ import annotations

from pydantic import Field

from runtime_common.settings import BaseRuntimeSettings


class Settings(BaseRuntimeSettings):
    service_name: str = "hermes-base"

    runtime_kind: str = Field(
        default="hermes",
        description="Hermes profile pool — deploy_mode=hermes_general only.",
    )
    hermes_work_dir: str = Field(
        default="/var/cache/hermes-work",
        description="Invoke scratch emptyDir root (HERMES_HOME parent).",
    )
    vfs_dsn: str = Field(
        default="",
        description="Postgres DSN for AsyncpgAgentVfsStore (VFS_DSN).",
    )
    vfs_pgbouncer: bool = Field(default=False)
    hermes_session_dsn: str = Field(
        default="",
        description="Postgres DSN for Hermes SessionDB (sessions.state_backend=postgres).",
    )
    mcp_gateway_url: str = Field(
        default="http://envoy.runtime.svc.cluster.local:8080",
        description="Envoy URL for MCP invoke-internal (runtime_mcp bridge).",
    )
    invoke_timeout_sec: int = Field(default=300)
    profile_lock_ttl_sec: int | None = Field(
        default=None,
        description="Redis lock TTL; defaults to invoke_timeout_sec + 30.",
    )

    @property
    def lock_ttl_sec(self) -> int:
        if self.profile_lock_ttl_sec is not None:
            return self.profile_lock_ttl_sec
        return self.invoke_timeout_sec + 30
