"""Request-scoped context for hermes-base."""

from __future__ import annotations

from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("hermes_current_token", default=None)


def get_current_token() -> str | None:
    return _current_token.get()


def set_current_token(token: str | None):
    return _current_token.set(token)


def reset_current_token(token) -> None:
    _current_token.reset(token)
