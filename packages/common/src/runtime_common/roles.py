"""User role hierarchy for the admin console."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    DEVELOPER = "developer"
    ADMIN = "admin"


_ROLE_RANK = {
    UserRole.USER: 0,
    UserRole.DEVELOPER: 1,
    UserRole.ADMIN: 2,
}


def parse_role(value: str | UserRole | None, *, fallback: UserRole = UserRole.USER) -> UserRole:
    if value is None:
        return fallback
    if isinstance(value, UserRole):
        return value
    try:
        return UserRole(value)
    except ValueError:
        return fallback


def role_at_least(role: str | UserRole, minimum: UserRole) -> bool:
    current = parse_role(role)
    return _ROLE_RANK[current] >= _ROLE_RANK[minimum]


def role_from_legacy_is_admin(is_admin: bool) -> UserRole:
    return UserRole.ADMIN if is_admin else UserRole.USER
