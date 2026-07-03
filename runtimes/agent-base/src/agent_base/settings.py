from pydantic import Field, field_validator

from runtime_common.settings import BaseRuntimeSettings


class Settings(BaseRuntimeSettings):
    service_name: str = "agent-base"

    runtime_kind: str = Field(
        default="compiled_graph",
        description="Which agent framework this pod hosts. One of AgentRuntimeKind values.",
    )
    bundle_cache_dir: str = Field(default="/var/cache/agent-bundles")
    invoke_timeout_sec: int = Field(default=120)
    job_invoke_timeout_sec: int = Field(
        default=7200,
        description="Async /jobs worker timeout; graph-extractor batch runs can exceed sync invoke.",
    )
    mcp_gateway_url: str = Field(
        default="http://mcp-gateway.runtime.svc.cluster.local:8080",
        description="MCP gateway URL for internal tool calls",
    )
    agent_gateway_url: str = Field(
        default="",
        description="Agent gateway URL for delegate calls. Falls back to MCP_GATEWAY_URL env.",
    )
    agent_delegate_timeout_sec: int = Field(default=60)
    max_delegate_depth: int = Field(default=3)
    vfs_dsn: str = Field(
        default="",
        description="Postgres DSN for VFS tables (asyncpg). Empty = VFS disabled.",
    )
    vfs_pgbouncer: bool = Field(
        default=False,
        description="PgBouncer-compatible asyncpg settings for VFS (statement_cache_size=0).",
    )
    checkpointer_dsn: str = Field(
        default="",
        description="Postgres DSN for LangGraph checkpoints. Falls back to VFS_DSN when empty.",
    )
    session_db_dsn: str = Field(
        default="",
        description="Postgres DSN for ADK DatabaseSessionService. Falls back to VFS_DSN when empty.",
    )
    warmup_agents: list[str] = Field(
        default_factory=list,
        description="Agent names to preload at startup (comma-separated via WARMUP_AGENTS env).",
    )
    admin_backend_url: str = Field(
        default="http://backend.runtime.svc.cluster.local:8000",
        description="Admin backend URL for pipeline binding resolve (cluster-internal).",
    )
    argo_server_url: str = Field(
        default="",
        description="Argo Workflows server base URL for job completion callbacks.",
    )
    argo_auth_token: str = Field(
        default="",
        description="Bearer token for Argo API (optional — in-cluster SA).",
    )
    agent_job_ttl_sec: int = Field(default=604_800, description="Redis TTL for agent jobs (7d).")

    @field_validator("warmup_agents", mode="before")
    @classmethod
    def parse_warmup(cls, v: object) -> object:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
