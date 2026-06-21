from pydantic import Field

from runtime_common.settings import DbRuntimeSettings


class Settings(DbRuntimeSettings):
    service_name: str = "deploy-api"

    resolve_cache_ttl_sec: float = Field(
        default=5.0, description="TTL for /v1/resolve in-memory cache"
    )
    resolve_cache_max: int = Field(
        default=2048, description="Max entries for /v1/resolve in-memory cache"
    )
