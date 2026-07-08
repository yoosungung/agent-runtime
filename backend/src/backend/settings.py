from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.dev.local"), extra="ignore")

    POSTGRES_DSN: str = ""
    POSTGRES_PGBOUNCER: bool = False

    AUTH_URL: str = ""

    # Admin bootstrap / allowlist
    ADMIN_USERNAMES: str = ""  # comma-separated fallback
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_TENANT: str = "dev"
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
    MAX_BUCKET_OBJECT_MB: int = 200
    BUNDLE_STORAGE_BACKEND: str = "local"  # k8s: "s3" via s3-creds secret (default Garage)

    # S3-compatible bundle storage (BUNDLE_STORAGE_BACKEND="s3")
    # k8s default: in-cluster Garage — see deploy/k8s/garage/
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""  # empty = AWS; k8s Garage: http://garage-s3.runtime.svc.cluster.local:3900
    S3_REGION: str = "us-east-1"
    S3_PREFIX: str = "bundles/"  # key prefix in bucket
    S3_ACCESS_KEY_ID: str = ""  # empty = use IAM/env credentials
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PRESIGN_EXPIRY_SEC: int = 3600

    # Envoy data-plane URL (routes /v1/agents/* and /v1/mcp/*)
    ENVOY_URL: str = "http://envoy.runtime.svc.cluster.local:8080"

    # Deploy-API URL (used when building K8s Deployment env for custom image mode)
    DEPLOY_API_URL: str = "http://deploy-api.runtime.svc.cluster.local:8080"

    # Kubernetes (used for custom image mode dynamic deployments)
    K8S_IN_CLUSTER: bool = True  # False = use kubeconfig (local dev)
    K8S_RUNTIME_NAMESPACE: str = "runtime"
    K8S_CLUSTER_DOMAIN: str = "cluster.local"
    # Reconciler: how long a 'pending' row may stay before forced cleanup
    K8S_PENDING_TIMEOUT_SEC: int = 300  # 5 minutes
    # How long to wait for Deployment to become ready during POST
    K8S_DEPLOY_READY_TIMEOUT_SEC: int = 60

    # Warm-registry Pub/Sub mirror for dashboard pool metrics (optional)
    REDIS_URL: str = ""

    # Feature flags
    ALLOW_HARD_DELETE: bool = False
    BACKEND_SERVE_SPA: bool = True

    # VFS admin (general agent /agent/ shared files)
    VFS_DSN: str = ""
    VFS_PGBOUNCER: bool = False

    # LangGraph checkpoint read (Recent Chats message hydrate)
    CHECKPOINTER_DSN: str = ""
    MAX_VFS_FILE_BYTES: int = 1_048_576  # 1 MiB
    MAX_WIKI_VFS_FILE_BYTES: int = 4_194_304  # 4 MiB

    # Pipeline admin console (path-graph sources / ingest)
    PIPELINE_CONSOLE_ENABLED: bool = True
    PATH_GRAPH_DSN: str = ""  # fallback: POSTGRES_DSN (psycopg postgresql://)
    PATH_GRAPH_ARGO_NAMESPACE: str = "path-graph"
    PATH_GRAPH_COLLECT_WF_TEMPLATE: str = "pipeline-collect-ingest-rag"
    PATH_GRAPH_COLLECT_ONLY_WF_TEMPLATE: str = "pipeline-collect"
    PATH_GRAPH_INGEST_WF_TEMPLATE: str = "pipeline-ingest-rag"
    PATH_GRAPH_GRAPHRAG_WF_TEMPLATE: str = "pipeline-graphrag"
    PATH_GRAPH_PURGE_PROJECT_WF_TEMPLATE: str = "pipeline-purge-project"
    PATH_GRAPH_DELETE_PROJECT_WF_TEMPLATE: str = "pipeline-delete-project"
    PATH_GRAPH_RECONCILE_WF_TEMPLATE: str = "pipeline-reconcile-index"
    PATH_GRAPH_RECONCILE_CRON_SCHEDULE: str = "0 3 * * *"
    PATH_GRAPH_WF_TEMPLATE: str = "pipeline-collect-ingest-rag"
    MAX_PIPELINE_RAW_UPLOAD_MB: int = 100
    PATH_GRAPH_CREDENTIAL_NAMESPACE: str = "path-graph"
    PIPELINE_CREDENTIAL_LOCAL_DIR: str = "/var/lib/admin/pipeline-credentials"
    PIPELINE_OAUTH_STATE_KEY: str = ""

    PIPELINE_GDRIVE_CLIENT_ID: str = ""
    PIPELINE_GDRIVE_CLIENT_SECRET: str = ""
    PIPELINE_GDRIVE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/pipeline/oauth/callback/gdrive"

    PIPELINE_MS_CLIENT_ID: str = ""
    PIPELINE_MS_CLIENT_SECRET: str = ""
    PIPELINE_MS_TENANT_ID: str = "common"
    PIPELINE_MS_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/pipeline/oauth/callback/microsoft"

    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
