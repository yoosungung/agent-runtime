from __future__ import annotations

import secrets


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf(header_value: str | None, cookie_value: str | None) -> bool:
    if not header_value or not cookie_value:
        return False
    return secrets.compare_digest(header_value, cookie_value)
