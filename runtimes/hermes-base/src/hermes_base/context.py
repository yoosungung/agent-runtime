"""Request-scoped context for hermes-base."""

from __future__ import annotations

from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("hermes_current_token", default=None)
_delegate_depth: ContextVar[int] = ContextVar("hermes_delegate_depth", default=0)


def get_current_token() -> str | None:
    return _current_token.get()


def get_current_delegate_depth() -> int:
    return _delegate_depth.get()


def set_current_token(token: str | None):
    return _current_token.set(token)


def set_current_delegate_depth(depth: int):
    return _delegate_depth.set(depth)


def reset_current_token(token) -> None:
    _current_token.reset(token)


def reset_current_delegate_depth(token) -> None:
    _delegate_depth.reset(token)
