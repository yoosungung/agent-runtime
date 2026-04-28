"""Bundle config schemas.

Single source of truth for source_meta.config and user_meta.config structure.
Bundle factories read from the merged cfg dict; admin backend validates on write.

Layout
------
Source (source_meta.config)  — immutable per version, set by bundle author / admin.
User   (user_meta.config)    — per-principal overrides, mutable; only allowed keys exposed.

Sections are namespaced by runtime kind so keys never collide across frameworks.
Infrastructure secrets (DSNs, API keys) go in secrets_ref, never in config.

secrets_ref key conventions (UPPERCASE — matches env var convention used by EnvSecretResolver):
  langgraph.checkpointer=postgres   → secrets_ref["CHECKPOINTER_DSN"]
  langgraph.store.backend=postgres  → secrets_ref["STORE_DSN"]
  langgraph.cache=redis             → secrets_ref["CACHE_DSN"]
  langgraph.store.index.embed=...   → secrets_ref["EMBED_API_KEY"]
  adk.session_service=database      → secrets_ref["SESSION_DB_DSN"]
  adk.memory_service=vertexai       → secrets_ref["VERTEXAI_CREDENTIALS"]
  adk.artifact_service=gcs          → secrets_ref["GCS_BUCKET"]
  fastmcp.session_state_store=redis → secrets_ref["SESSION_REDIS_DSN"]
  fastmcp.task_queue=redis          → secrets_ref["TASK_REDIS_DSN"]
LLM API keys are also resolved via secrets_ref (e.g. ANTHROPIC_API_KEY, GOOGLE_API_KEY).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── LangGraph / DeepAgents (agent:compiled_graph) ────────────────────────────

class StoreIndexConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embed: str | None = Field(
        default=None,
        description="Embedding model spec, e.g. 'openai:text-embedding-3-small'. "
                    "None disables vector search.",
    )
    dims: int | None = Field(default=None, description="Embedding dimensions.")


class StoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["none", "memory", "postgres", "redis"] = "none"
    index: StoreIndexConfig = Field(default_factory=StoreIndexConfig)


class LangGraphSourceConfig(BaseModel):
    """source_meta.config['langgraph'] — compile-time infra wiring for compiled_graph."""

    model_config = ConfigDict(extra="forbid")

    recursion_limit: int = Field(
        default=100,
        ge=1,
        description="Max graph steps before GraphRecursionError.",
    )
    checkpointer: Literal["none", "memory", "sqlite", "postgres", "mongo", "redis"] = Field(
        default="none",
        description="Checkpoint backend. DSN supplied via secrets_ref['checkpointer_dsn'].",
    )
    store: StoreConfig = Field(
        default_factory=StoreConfig,
        description="Cross-thread memory store. DSN via secrets_ref['store_dsn'].",
    )
    cache: Literal["none", "memory", "sqlite", "redis"] = Field(
        default="none",
        description="Node-result cache. DSN via secrets_ref['cache_dsn'].",
    )
    model: str | None = Field(
        default=None,
        description="LLM model spec for DeepAgents, e.g. 'anthropic:claude-sonnet-4-6'. "
                    "Ignored by plain compiled_graph bundles.",
    )


class LangGraphUserConfig(BaseModel):
    """user_meta.config['langgraph'] — allowed per-principal overrides."""

    model_config = ConfigDict(extra="forbid")

    recursion_limit: int | None = Field(default=None, ge=1)
    model: str | None = None


# ── Google ADK (agent:adk) ───────────────────────────────────────────────────

class AdkSourceConfig(BaseModel):
    """source_meta.config['adk'] — infra wiring for ADK agents."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(
        default="google:gemini-2.0-flash",
        description="LLM model spec, e.g. 'google:gemini-2.0-flash' or 'anthropic:claude-sonnet-4-6'.",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=8192, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    max_llm_calls: int = Field(
        default=500,
        ge=0,
        description="Hard cap on LLM calls per run. 0 = unlimited.",
    )
    session_service: Literal["memory", "database", "vertexai"] = Field(
        default="memory",
        description="Session storage backend. DSN via secrets_ref['session_db_dsn'].",
    )
    memory_service: Literal["memory", "vertexai"] = Field(
        default="memory",
        description="Cross-session memory backend. Credentials via secrets_ref['vertexai_credentials'].",
    )
    artifact_service: Literal["memory", "gcs", "database"] = Field(
        default="memory",
        description="Artifact storage backend. Credentials via secrets_ref['gcs_credentials'].",
    )


class AdkUserConfig(BaseModel):
    """user_meta.config['adk'] — allowed per-principal overrides."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_llm_calls: int | None = Field(default=None, ge=0)


# ── FastMCP (mcp:fastmcp) ────────────────────────────────────────────────────

class FastMcpSourceConfig(BaseModel):
    """source_meta.config['fastmcp'] — server-level options for FastMCP bundles."""

    model_config = ConfigDict(extra="forbid")

    strict_input_validation: bool = Field(
        default=False,
        description="Enforce strict JSON Schema validation on tool inputs.",
    )
    mask_error_details: bool = Field(
        default=False,
        description="Hide internal error details from MCP clients (production hardening).",
    )
    list_page_size: int | None = Field(
        default=None,
        ge=1,
        description="Pagination size for tool/resource listings. None = no pagination.",
    )
    session_state_store: Literal["memory", "redis"] = Field(
        default="memory",
        description="Per-session key-value store. DSN via secrets_ref['session_redis_dsn'].",
    )
    task_queue: Literal["memory", "redis", "valkey"] = Field(
        default="memory",
        description="Background task queue backend. DSN via secrets_ref['task_redis_dsn'].",
    )
    task_concurrency: int = Field(
        default=10,
        ge=1,
        description="Max concurrent background tasks per server instance.",
    )


# FastMCP has no meaningful per-principal overrides (MCP is stateless per tool call).


# ── MCP SDK (mcp:mcp_sdk) ────────────────────────────────────────────────────

class McpSdkSourceConfig(BaseModel):
    """source_meta.config['mcp'] — options for low-level MCP SDK bundles."""

    model_config = ConfigDict(extra="forbid")

    mask_error_details: bool = Field(
        default=False,
        description="Hide internal error details from MCP clients.",
    )


# ── Root config models ────────────────────────────────────────────────────────

class SourceConfig(BaseModel):
    """Full schema for source_meta.config.

    Only the section matching the bundle's runtime_pool is used at runtime.
    All sections present so the admin UI can render forms for any runtime kind.

    ``extra="allow"`` at the root: bundle authors may add their own top-level
    keys (e.g. ``"mcp_server"`` to indicate which MCP server an agent calls,
    or ``"naver"`` for Naver API credentials). Inside the standard sections
    (langgraph/adk/fastmcp/mcp) extras are still rejected.
    """

    model_config = ConfigDict(extra="allow")

    timeout_seconds: int = Field(default=60, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    langgraph: LangGraphSourceConfig = Field(default_factory=LangGraphSourceConfig)
    adk: AdkSourceConfig = Field(default_factory=AdkSourceConfig)
    fastmcp: FastMcpSourceConfig = Field(default_factory=FastMcpSourceConfig)
    mcp: McpSdkSourceConfig = Field(default_factory=McpSdkSourceConfig)


class UserConfig(BaseModel):
    """Schema for user_meta.config.

    All fields optional; only set when overriding source defaults.
    Sections not present are ignored during merge. Like SourceConfig, root-level
    extras are allowed so per-principal overrides can target bundle-specific keys.
    """

    model_config = ConfigDict(extra="allow")

    timeout_seconds: int | None = Field(default=None, ge=1)

    langgraph: LangGraphUserConfig | None = None
    adk: AdkUserConfig | None = None
    # fastmcp / mcp: no per-principal overrides
