"""Google ADK infra providers.

Reads ``cfg["adk"]`` (validated against ``AdkSourceConfig``) and materialises
ADK service objects + ``GenerateContentConfig`` for ``LlmAgent``.

Bundle authors call these inside their factory and feed the returned objects
into ``LlmAgent(...)`` and (eventually) ``Runner(...)`` construction.
"""

from __future__ import annotations

from typing import Any

from runtime_common.secrets import SecretResolver


def _section(cfg: dict) -> dict:
    return cfg.get("adk") or {}


def get_model(cfg: dict) -> str:
    return _section(cfg).get("model", "google:gemini-2.0-flash")


def get_max_llm_calls(cfg: dict) -> int:
    return int(_section(cfg).get("max_llm_calls", 500))


def build_generate_content_config(cfg: dict) -> Any:
    """Map ``cfg.adk.{temperature,max_output_tokens,top_p,top_k}`` to GenerateContentConfig."""
    from google.genai import types as genai_types

    section = _section(cfg)
    kwargs: dict[str, Any] = {
        "temperature": float(section.get("temperature", 0.0)),
        "max_output_tokens": int(section.get("max_output_tokens", 8192)),
    }
    if section.get("top_p") is not None:
        kwargs["top_p"] = float(section["top_p"])
    if section.get("top_k") is not None:
        kwargs["top_k"] = int(section["top_k"])
    return genai_types.GenerateContentConfig(**kwargs)


def build_session_service(cfg: dict, secrets: SecretResolver) -> Any:
    """Build ADK session service from ``cfg.adk.session_service``."""
    backend = _section(cfg).get("session_service", "memory")
    if backend == "memory":
        from google.adk.sessions import InMemorySessionService

        return InMemorySessionService()
    if backend == "database":
        from google.adk.sessions import DatabaseSessionService

        return DatabaseSessionService(db_url=secrets.resolve("SESSION_DB_DSN"))
    if backend == "vertexai":
        from google.adk.sessions import VertexAiSessionService

        return VertexAiSessionService()
    raise ValueError(f"unsupported session_service: {backend!r}")


def build_memory_service(cfg: dict, secrets: SecretResolver) -> Any:
    """Build ADK memory service from ``cfg.adk.memory_service``."""
    backend = _section(cfg).get("memory_service", "memory")
    if backend == "memory":
        from google.adk.memory import InMemoryMemoryService

        return InMemoryMemoryService()
    if backend == "vertexai":
        from google.adk.memory import VertexAiMemoryBankService

        return VertexAiMemoryBankService()
    raise ValueError(f"unsupported memory_service: {backend!r}")


def build_artifact_service(cfg: dict, secrets: SecretResolver) -> Any:
    """Build ADK artifact service from ``cfg.adk.artifact_service``."""
    backend = _section(cfg).get("artifact_service", "memory")
    if backend == "memory":
        from google.adk.artifacts import InMemoryArtifactService

        return InMemoryArtifactService()
    if backend == "gcs":
        from google.adk.artifacts import GcsArtifactService

        return GcsArtifactService(bucket_name=secrets.resolve("GCS_BUCKET"))
    if backend == "database":
        # ADK >=1.30 ships a database-backed artifact service.
        from google.adk.artifacts import DatabaseArtifactService  # type: ignore[attr-defined]

        return DatabaseArtifactService(db_url=secrets.resolve("ARTIFACT_DB_DSN"))
    raise ValueError(f"unsupported artifact_service: {backend!r}")
