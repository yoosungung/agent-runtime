from pydantic import Field

from runtime_common.settings import BaseRuntimeSettings


class Settings(BaseRuntimeSettings):
    service_name: str = "mcp-base"

    runtime_kind: str = Field(
        default="fastmcp",
        description="Which MCP framework this pod hosts. One of McpRuntimeKind values.",
    )
    bundle_cache_dir: str = Field(default="/var/cache/mcp-bundles")
