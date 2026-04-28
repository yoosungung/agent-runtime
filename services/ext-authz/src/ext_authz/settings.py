from pydantic import Field

from runtime_common.settings import BaseRuntimeSettings


class Settings(BaseRuntimeSettings):
    service_name: str = Field(default="ext-authz")

    # Agent pool service URLs — used as ring-hash fallback when warm-registry miss.
    # 'custom' is omitted: image-mode pools are derived from slug at runtime.
    pool_compiled_graph_url: str = Field(
        default="http://agent-pool-compiled-graph.runtime.svc.cluster.local:8080"
    )
    pool_adk_url: str = Field(default="http://agent-pool-adk.runtime.svc.cluster.local:8080")

    # MCP pool service URLs.
    pool_fastmcp_url: str = Field(default="http://mcp-pool-fastmcp.runtime.svc.cluster.local:8080")
    pool_mcp_sdk_url: str = Field(default="http://mcp-pool-mcp-sdk.runtime.svc.cluster.local:8080")

    # K8s cluster domain suffix — used to build image-mode pool Service URLs.
    cluster_domain: str = Field(default="cluster.local")
    runtime_namespace: str = Field(default="runtime")

    # Grace for mcp internal route — path-determined by ext_authz.
    mcp_internal_grace_sec: int = Field(default=300)

    # Rate limits (per-minute).
    rate_limit_per_principal: int = Field(default=60)
    rate_limit_per_resource: int = Field(default=120)

    def agent_pool_url(self, runtime_kind: str) -> str | None:
        """Return bundle-mode pool Service URL, or None for image mode."""
        return {
            "compiled_graph": self.pool_compiled_graph_url,
            "adk": self.pool_adk_url,
        }.get(runtime_kind)

    def mcp_pool_url(self, runtime_kind: str) -> str | None:
        """Return bundle-mode pool Service URL, or None for image mode."""
        return {
            "fastmcp": self.pool_fastmcp_url,
            "mcp_sdk": self.pool_mcp_sdk_url,
        }.get(runtime_kind)

    def image_mode_pool_url(self, kind: str, slug: str) -> str:
        """Derive image-mode pool Service URL from kind and slug.

        Format: http://{kind}-pool-custom-{slug}.{namespace}.svc.{cluster_domain}:8080
        No envvar lookup — DNS-derived so no ext-authz restart needed on new image registration.
        """
        svc = f"{kind}-pool-custom-{slug}"
        return f"http://{svc}.{self.runtime_namespace}.svc.{self.cluster_domain}:8080"
