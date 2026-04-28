from pydantic import Field

from runtime_common.settings import BaseRuntimeSettings


class Settings(BaseRuntimeSettings):
    service_name: str = Field(default="ext-authz")

    # Agent pool service URLs — used as ring-hash fallback when warm-registry miss.
    pool_compiled_graph_url: str = Field(
        default="http://agent-pool-compiled-graph.runtime.svc.cluster.local:8080"
    )
    pool_adk_url: str = Field(default="http://agent-pool-adk.runtime.svc.cluster.local:8080")
    pool_custom_url: str = Field(default="http://agent-pool-custom.runtime.svc.cluster.local:8080")

    # MCP pool service URLs.
    pool_fastmcp_url: str = Field(default="http://mcp-pool-fastmcp.runtime.svc.cluster.local:8080")
    pool_mcp_sdk_url: str = Field(default="http://mcp-pool-mcp-sdk.runtime.svc.cluster.local:8080")
    pool_mcp_custom_url: str = Field(
        default="http://mcp-pool-custom.runtime.svc.cluster.local:8080"
    )

    # Grace for mcp internal route — path-determined by ext_authz.
    mcp_internal_grace_sec: int = Field(default=300)

    # Rate limits (per-minute).
    rate_limit_per_principal: int = Field(default=60)
    rate_limit_per_resource: int = Field(default=120)

    def agent_pool_url(self, runtime_kind: str) -> str | None:
        return {
            "compiled_graph": self.pool_compiled_graph_url,
            "adk": self.pool_adk_url,
            "custom": self.pool_custom_url,
        }.get(runtime_kind)

    def mcp_pool_url(self, runtime_kind: str) -> str | None:
        return {
            "fastmcp": self.pool_fastmcp_url,
            "mcp_sdk": self.pool_mcp_sdk_url,
            "custom": self.pool_mcp_custom_url,
        }.get(runtime_kind)
