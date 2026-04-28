from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    POSTGRES_DSN: str = ""
    POSTGRES_PGBOUNCER: bool = False

    AUTH_URL: str = ""

    # Admin bootstrap / allowlist
    ADMIN_USERNAMES: str = ""  # comma-separated fallback
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str = ""
    INITIAL_ADMIN_PASSWORD_FILE: str = "/etc/backend/initial-admin-password"

    # Password policy
    PASSWORD_MIN_LENGTH: int = 12

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    # Session / CSRF
    SESSION_COOKIE_SECURE: bool = True
    CSRF_COOKIE_NAME: str = "csrf_token"
    ACCESS_TOKEN_COOKIE: str = "access_token"
    REFRESH_TOKEN_COOKIE: str = "refresh_token"

    # Bundle storage
    BUNDLE_STORAGE_DIR: str = "/var/lib/admin/bundles"
    BUNDLE_PUBLIC_BASE_URL: str = ""
    MAX_BUNDLE_SIZE_MB: int = 200
    MAX_DECOMPRESSED_MB: int = 500
    BUNDLE_STORAGE_BACKEND: str = "local"  # "local" | "s3"

    # S3/MinIO bundle storage (used when BUNDLE_STORAGE_BACKEND="s3")
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""  # empty = AWS; set for MinIO e.g. http://minio:9000
    S3_REGION: str = "us-east-1"
    S3_PREFIX: str = "bundles/"  # key prefix in bucket
    S3_ACCESS_KEY_ID: str = ""  # empty = use IAM/env credentials
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PRESIGN_EXPIRY_SEC: int = 3600

    # Envoy data-plane URL (routes /v1/agents/* and /v1/mcp/*)
    ENVOY_URL: str = "http://envoy.runtime.svc.cluster.local:8080"

    # Feature flags
    ALLOW_HARD_DELETE: bool = False
    BACKEND_SERVE_SPA: bool = True

    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
