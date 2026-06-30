"""Request-scoped context for agent-base."""

from __future__ import annotations

from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)
_delegate_depth: ContextVar[int] = ContextVar("delegate_depth", default=0)


def get_current_token() -> str | None:
    """Return the JWT for the current request (for MCP JWT forwarding)."""
    return _current_token.get()


def get_delegate_depth() -> int:
    """Return nested agent-delegate depth for the current request."""
    return _delegate_depth.get()


def set_current_token(token: str | None):
    """Set request-scoped JWT; returns context token for reset."""
    return _current_token.set(token)


def set_delegate_depth(depth: int):
    """Set request-scoped delegate depth; returns context token for reset."""
    return _delegate_depth.set(depth)


def reset_current_token(token) -> None:
    _current_token.reset(token)


def reset_delegate_depth(token) -> None:
    _delegate_depth.reset(token)
