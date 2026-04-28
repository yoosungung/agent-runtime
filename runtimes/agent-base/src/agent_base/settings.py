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
    mcp_gateway_url: str = Field(
        default="http://mcp-gateway.runtime.svc.cluster.local:8080",
        description="MCP gateway URL for internal tool calls",
    )
    warmup_agents: list[str] = Field(
        default_factory=list,
        description="Agent names to preload at startup (comma-separated via WARMUP_AGENTS env).",
    )

    @field_validator("warmup_agents", mode="before")
    @classmethod
    def parse_warmup(cls, v: object) -> object:
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
