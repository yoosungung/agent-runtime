"""Request-scoped context for agent-base."""

from __future__ import annotations

from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)


def get_current_token() -> str | None:
    """Return the JWT for the current request (for MCP JWT forwarding)."""
    return _current_token.get()


def set_current_token(token: str | None):
    """Set request-scoped JWT; returns context token for reset."""
    return _current_token.set(token)


def reset_current_token(token) -> None:
    _current_token.reset(token)
