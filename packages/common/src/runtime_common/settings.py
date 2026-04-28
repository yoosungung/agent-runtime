import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = Field(default="runtime-service")
    env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    auth_service_url: str = Field(default="http://auth.runtime.svc.cluster.local:8080")
    deploy_api_url: str = Field(default="http://deploy-api.runtime.svc.cluster.local:8080")

    jwt_public_key: str | None = Field(default=None)
    jwt_issuer: str = Field(default="agents-runtime")

    redis_url: str = Field(default="redis://redis.runtime.svc.cluster.local:6379")

    otlp_endpoint: str | None = Field(default=None)

    # Opik LLM observability (pool runtimes only; ignored by gateway/auth/deploy-api)
    opik_url: str | None = Field(default=None)
    opik_workspace: str = Field(default="default")

    # Pool-base settings (ignored by non-pool services)
    pod_name: str = Field(
        default_factory=lambda: os.environ.get("POD_NAME", os.environ.get("HOSTNAME", "local"))
    )
    pod_ip: str = Field(default_factory=lambda: os.environ.get("POD_IP", "127.0.0.1"))
    pod_port: int = Field(default=8080)
    max_concurrent: int = Field(default=32)
    registry_heartbeat_interval_sec: int = Field(default=2)
    registry_ttl_sec: int = Field(default=3)
    bundle_cache_max: int = Field(default=16)
    bundle_verify_signatures: bool = Field(default=False)
    bundle_signing_public_key: str | None = Field(default=None)


class DbRuntimeSettings(BaseRuntimeSettings):
    """Settings for services that access Postgres (auth, deploy-api)."""

    postgres_dsn: str = Field(
        default="postgresql+asyncpg://runtime:runtime@localhost:5432/runtime",
    )
    # Read replica DSN (optional). Falls back to postgres_dsn when not set.
    postgres_read_dsn: str | None = Field(default=None)
    # Enable PgBouncer-compatible engine settings (disables asyncpg prepared statement cache).
    postgres_pgbouncer: bool = Field(default=False)
