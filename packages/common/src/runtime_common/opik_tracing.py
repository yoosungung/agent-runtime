from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

try:
    import opik as _opik

    _OPIK_AVAILABLE = True
except ImportError:
    _opik = None  # type: ignore[assignment]
    _OPIK_AVAILABLE = False

# Set to True only when configure_opik() receives a non-empty URL.
# Prevents sending traces to comet.com cloud when OPIK_URL is not configured.
_CONFIGURED = False


def configure_opik(url: str | None, workspace: str = "default") -> None:
    """Initialize Opik SDK via environment variables.

    No-op when *url* is None or opik is not installed — services without Opik
    configuration start normally without leaking traces to comet.com cloud.
    """
    global _CONFIGURED
    if not _OPIK_AVAILABLE or not url:
        return
    os.environ.setdefault("OPIK_URL_OVERRIDE", url)
    os.environ.setdefault("OPIK_WORKSPACE", workspace)
    _CONFIGURED = True
    logger.info("opik_configured", extra={"url": url, "workspace": workspace})


def is_opik_enabled() -> bool:
    """Return True only when Opik is installed AND configure_opik() succeeded."""
    return _OPIK_AVAILABLE and _CONFIGURED


@contextmanager
def opik_trace_context(
    name: str,
    project_name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[None, None, None]:
    """Open an Opik trace for the duration of the block.

    Opik uses ``contextvars.ContextVar`` internally, so each asyncio task (i.e.
    each FastAPI request) gets an isolated trace — no cross-request leakage.

    No-op when Opik is not installed or not configured via configure_opik().
    """
    if not is_opik_enabled():
        yield
        return

    meta: dict[str, Any] = {}
    if user_id:
        meta["user_id"] = user_id
    if metadata:
        meta.update(metadata)

    with _opik.start_as_current_trace(
        name=name,
        project_name=project_name,
        thread_id=session_id,
        metadata=meta or None,
    ):
        yield


@contextmanager
def opik_span_context(
    name: str,
    project_name: str,
    span_type: str = "tool",
    input_data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Open an Opik span for a single tool call, yielding the SpanData object.

    The caller can call ``span.update(output=result)`` after the tool runs.
    Yields None when Opik is not configured — caller must guard with ``if span:``.

    Used by mcp-base where the outer trace is managed by agent-base (or absent).
    """
    if not is_opik_enabled():
        yield None
        return

    with _opik.start_as_current_span(
        name=name,
        type=span_type,  # type: ignore[arg-type]
        project_name=project_name,
        input=input_data,
        metadata=metadata,
    ) as span_data:
        yield span_data
