from pydantic import Field

from runtime_common.settings import DbRuntimeSettings


class Settings(DbRuntimeSettings):
    service_name: str = "auth"

    jwt_private_key: str | None = Field(default=None, description="PEM private key for JWT signing")
    grace_max_sec: int = Field(
        default=600, description="Maximum grace period for internal token expiry"
    )
    access_cache_ttl_sec: float = Field(
        default=5.0, description="TTL for user→access in-memory cache"
    )
    refresh_token_ttl_days: int = Field(default=30, description="Refresh token lifetime in days")
