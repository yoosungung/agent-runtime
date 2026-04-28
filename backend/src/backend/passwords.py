from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()

COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password123",
        "12345678",
        "123456789",
        "admin",
        "admin123",
        "qwerty",
        "qwerty123",
        "letmein",
    }
)


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def check_policy(plain: str, min_length: int = 12) -> None:
    if len(plain) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters")
    if plain.lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common")
