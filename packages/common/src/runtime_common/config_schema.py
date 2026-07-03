"""Bundle config schemas.

Single source of truth for source_meta.config and user_meta.config structure.
Bundle factories read from the merged cfg dict; admin backend validates on write.

Layout — deploy (source) vs invoke (user)
-----------------------------------------
Source (source_meta.config)  — set at registration / startup. Shared resources,
  provider wiring, and credentials every principal needs for the agent/MCP to run.
User   (user_meta.config)    — set per principal. Identity and overrides applied
  at invoke time (mailbox uid, OAuth refresh token, quota, tone). Mutable.

Example (email-server MCP):
  source_meta.config  → provider=outlook, tenant_id, client_id, client_secret
  user_meta.config    → mailbox, refresh_token, from_address (per user)

Tool call arguments (folder, limit, query) are invoke payload — not user_meta.

Sections are namespaced by runtime kind so keys never collide across frameworks.
Shared service credentials may live in source_meta.config; principal-bound
credentials belong in user_meta.config or user_meta.secrets_ref.

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
        default="postgres",
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
        description="LLM model spec for DeepAgents, e.g. 'anthropic:claude-sonnet-4-6' or 'preset:MY_PRESET'. "
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
        description="LLM model spec, e.g. 'google:gemini-2.0-flash', 'anthropic:claude-sonnet-4-6', or 'preset:MY_PRESET'.",
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
        default="database",
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


# ── Email MCP (mcp:mcp_sdk — email_bundle) ───────────────────────────────────


class EmailSourceConfig(BaseModel):
    """source_meta.config['email'] — provider selection and shared defaults."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["imap", "pop3", "outlook", "gmail"]
    default_folder: str = "INBOX"
    page_size: int = Field(default=25, ge=1, le=50)
    body_max_bytes: int = Field(default=32768, ge=1)
    from_address: str | None = Field(
        default=None,
        description="Default From address when not overridden per principal.",
    )


class EmailUserConfig(BaseModel):
    """user_meta.config['email'] — per-principal mailbox identity."""

    model_config = ConfigDict(extra="forbid")

    from_address: str | None = None


class OutlookSourceConfig(BaseModel):
    """source_meta.config['outlook'] — Microsoft Graph app registration (shared)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    client_id: str
    client_secret: str | None = None
    client_secret_ref: str | None = Field(
        default=None,
        description="Env var name resolved via SecretResolver when client_secret omitted.",
    )
    auth: Literal["client_credentials", "oauth_refresh"] = "client_credentials"
    mailbox: str | None = Field(
        default=None,
        description="Shared mailbox for client_credentials mode.",
    )


class OutlookUserConfig(BaseModel):
    """user_meta.config['outlook'] — delegated mailbox credentials."""

    model_config = ConfigDict(extra="forbid")

    mailbox: str | None = None
    refresh_token: str | None = None


class GmailSourceConfig(BaseModel):
    """source_meta.config['gmail'] — Gmail API app registration (shared)."""

    model_config = ConfigDict(extra="forbid")

    auth: Literal["service_account", "oauth_refresh"] = "service_account"
    client_id: str | None = None
    client_secret: str | None = None
    client_secret_ref: str | None = None
    subject_email: str | None = Field(
        default=None,
        description="Delegated subject for service_account mode.",
    )


class GmailUserConfig(BaseModel):
    """user_meta.config['gmail'] — per-principal OAuth refresh."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None


# ── Search MCP (mcp:mcp_sdk — search_bundle) ─────────────────────────────────


class SearchSourceConfig(BaseModel):
    """source_meta.config['search'] — Naver search defaults."""

    model_config = ConfigDict(extra="forbid")

    max_display: int = Field(default=10, ge=1, le=100)
    default_category: Literal["web", "blog", "news"] = "web"


class NaverSourceConfig(BaseModel):
    """source_meta.config['naver'] — Naver OpenAPI app credentials (shared)."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_secret: str | None = None
    client_secret_ref: str | None = Field(
        default=None,
        description="Env var name resolved via SecretResolver when client_secret omitted.",
    )


class FetchSourceConfig(BaseModel):
    """source_meta.config['fetch'] — fetch_url safety and limits."""

    model_config = ConfigDict(extra="forbid")

    max_bytes: int = Field(default=8192, ge=1)
    timeout_seconds: float = Field(default=10.0, gt=0)
    user_agent: str = "agents-runtime-search-bundle/1.0"
    allow_private_network: bool = False
    max_redirects: int = Field(default=5, ge=0, le=10)


# ── Knowledge policy (MCP registration) ───────────────────────────────────────


class KnowledgePolicyConfig(BaseModel):
    """source_meta.config['knowledge'] — MCP knowledge binding policy."""

    model_config = ConfigDict(extra="forbid")

    requires_project: bool = Field(
        default=False,
        description="When true, general agents using this MCP must bind pipeline projects.",
    )


# ── General Agent (deploy_mode: general) ─────────────────────────────────────


class GeneralVfsConfig(BaseModel):
    """VFS routing is platform-fixed (/, /agent/, /user/). Minimal user config."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    wiki_enabled: bool = Field(
        default=True,
        description="Mount pipeline wiki VFS when knowledge_project_ids is non-empty.",
    )


class McpToolManifestEntry(BaseModel):
    """Cached tool descriptor from MCP discovery at registration time."""

    model_config = ConfigDict(extra="forbid")

    server: str
    name: str
    description: str = ""


class GeneralAgentSourceConfig(BaseModel):
    """source_meta.config['general'] — config-only agent (no bundle)."""

    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(..., min_length=1)
    mcp_servers: list[str] = Field(..., min_length=1)
    mcp_tools: list[McpToolManifestEntry] = Field(
        default_factory=list,
        description="Populated at registration via MCP tool discovery.",
    )
    vfs: GeneralVfsConfig = Field(default_factory=GeneralVfsConfig)
    knowledge_project_ids: list[str] = Field(
        default_factory=list,
        description="Pipeline project UUIDs — knowledge boundary for MCP retrieval and wiki VFS.",
    )
    mcp_requires_knowledge: list[str] = Field(
        default_factory=list,
        description="MCP server names that required knowledge projects at registration (cached).",
    )
    subagents: list[dict] | None = Field(
        default=None,
        description="Optional deepagents subagent specs.",
    )
    delegate_agents: list[str] = Field(
        default_factory=list,
        description="Platform agent names this orchestrator may invoke via invoke-internal.",
    )
    allow_agent_delegation: bool = Field(
        default=True,
        description="When false, delegate tools are not exposed at runtime.",
    )


class GeneralAgentUserConfig(BaseModel):
    """user_meta.config['general'] — per-principal overrides for general agents."""

    model_config = ConfigDict(extra="forbid")

    system_prompt: str | None = None
    langgraph: LangGraphUserConfig | None = None


class HermesMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class HermesGeneralSourceConfig(BaseModel):
    """source_meta.config['hermes'] — Hermes profile agent (no bundle)."""

    model_config = ConfigDict(extra="forbid")

    soul: str = Field(..., min_length=1)
    model: str = ""
    mcp_servers: list[str] = Field(..., min_length=1)
    mcp_tools: list[McpToolManifestEntry] = Field(default_factory=list)
    enabled_toolsets: list[str] = Field(default_factory=lambda: ["web", "runtime_mcp"])
    skills: list[str] = Field(default_factory=list)
    memory: HermesMemoryConfig = Field(default_factory=HermesMemoryConfig)
    max_iterations: int = Field(default=90, ge=1, le=200)


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
    delegate_agents: list[str] = Field(
        default_factory=list,
        description="Platform agent names this bundle may invoke via invoke-internal.",
    )
    allow_agent_delegation: bool = Field(
        default=True,
        description="When false, delegate tools are not exposed at runtime.",
    )

    langgraph: LangGraphSourceConfig = Field(default_factory=LangGraphSourceConfig)
    adk: AdkSourceConfig = Field(default_factory=AdkSourceConfig)
    fastmcp: FastMcpSourceConfig = Field(default_factory=FastMcpSourceConfig)
    mcp: McpSdkSourceConfig = Field(default_factory=McpSdkSourceConfig)
    general: GeneralAgentSourceConfig | None = None
    hermes: HermesGeneralSourceConfig | None = None
    email: EmailSourceConfig | None = None
    outlook: OutlookSourceConfig | None = None
    gmail: GmailSourceConfig | None = None
    search: SearchSourceConfig | None = None
    naver: NaverSourceConfig | None = None
    fetch: FetchSourceConfig | None = None
    knowledge: KnowledgePolicyConfig = Field(default_factory=KnowledgePolicyConfig)


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
    general: GeneralAgentUserConfig | None = None
    email: EmailUserConfig | None = None
    outlook: OutlookUserConfig | None = None
    gmail: GmailUserConfig | None = None
    # fastmcp / mcp SDK sections: no per-principal overrides beyond bundle-specific keys


# ── user_meta form template (admin UI — not merged at runtime) ───────────────


class UserMetaFormField(BaseModel):
    """Single field in the end-user user_meta input form."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1, description="Dot path in user_meta.config")
    label: str = Field(..., min_length=1)
    type: Literal["string", "password", "number", "boolean"] = "string"
    required: bool = False
    placeholder: str | None = None
    help: str | None = None


class UserMetaFormTemplate(BaseModel):
    """Admin-defined form template shown to users at /me/user-meta."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    description: str | None = None
    fields: list[UserMetaFormField] = Field(default_factory=list)
    secrets_ref_enabled: bool = False
    secrets_ref_help: str | None = None


def is_user_meta_required(template: UserMetaFormTemplate) -> bool:
    """Return False when admin marked user_meta as not needed for this resource."""
    if template.enabled is not None:
        return template.enabled
    return bool(template.fields) or template.secrets_ref_enabled


def get_nested_config(config: dict, path: str) -> object | None:
    """Return a value from a nested dict using dot-separated *path*."""
    current: object = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def validate_template_required_fields(template: UserMetaFormTemplate, config: dict) -> None:
    """Raise ValueError when a required template field is missing from *config*."""
    if not is_user_meta_required(template):
        return
    missing: list[str] = []
    for field in template.fields:
        if not field.required:
            continue
        value = get_nested_config(config, field.path)
        if value is None or value == "":
            missing.append(field.path)
    if missing:
        raise ValueError(f"Missing required user_meta fields: {', '.join(missing)}")


# ── infra_meta (platform env) ───────────────────────────────────────────────


class InfraConfig(BaseModel):
    """Curated UI fields for Platform Infra — maps to flat container env keys.

    API/DB/K8s use flat env var names (``OPIK_URL``, …). This model documents
    the admin UI form only; validation is ``infra_env.validate_infra_env_patch``.
    """

    model_config = ConfigDict(extra="forbid")

    opik_url: str | None = Field(
        default=None,
        description="Opik server URL → OPIK_URL",
    )
    opik_workspace: str = Field(
        default="default",
        description="Opik workspace → OPIK_WORKSPACE",
    )
    default_llm_model: str | None = Field(
        default=None,
        description="Optional platform default model spec → DEFAULT_LLM_MODEL",
    )
    openai_api_base: str | None = Field(
        default=None,
        description="OpenAI-compatible base URL for vLLM/SGLang → OPENAI_API_BASE",
    )
    llm_runtime: str | None = Field(
        default=None,
        description="Self-hosted runtime hint (vllm|sglang) → LLM_RUNTIME",
    )
    otlp_endpoint: str | None = Field(
        default=None,
        description="Pool OTLP endpoint override → OTLP_ENDPOINT",
    )
