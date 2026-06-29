"""Hermes profile config — mirrors future runtime_common.config_schema.HermesGeneralSourceConfig."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HermesMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class McpToolManifestEntry(BaseModel):
    server: str
    name: str
    description: str = ""


class HermesGeneralSourceConfig(BaseModel):
    """source_meta.config['hermes'] — config-only Hermes profile agent."""

    model_config = ConfigDict(extra="forbid")

    soul: str = Field(..., min_length=1)
    model: str = ""
    mcp_servers: list[str] = Field(..., min_length=1)
    mcp_tools: list[McpToolManifestEntry] = Field(default_factory=list)
    enabled_toolsets: list[str] = Field(default_factory=lambda: ["web", "runtime_mcp"])
    skills: list[str] = Field(default_factory=list)
    memory: HermesMemoryConfig = Field(default_factory=HermesMemoryConfig)
    max_iterations: int = Field(default=90, ge=1, le=200)


def parse_hermes_cfg(cfg: dict) -> HermesGeneralSourceConfig:
    raw = cfg.get("hermes") or {}
    if not raw.get("soul"):
        raise ValueError("hermes agent requires config.hermes.soul")
    if not raw.get("mcp_servers"):
        raise ValueError("hermes agent requires config.hermes.mcp_servers")
    return HermesGeneralSourceConfig.model_validate(raw)
