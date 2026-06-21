"""Tests for runtime_common.providers.adk."""

import pytest

from runtime_common.providers.adk import sqlalchemy_asyncpg_dsn


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@localhost/db",
            "postgresql+asyncpg://u:p@localhost/db",
        ),
        (
            "postgresql://u:p@localhost/db?sslmode=disable",
            "postgresql+asyncpg://u:p@localhost/db?sslmode=disable",
        ),
        (
            "postgresql+asyncpg://u:p@localhost/db",
            "postgresql+asyncpg://u:p@localhost/db",
        ),
        (
            "postgres://u:p@localhost/db",
            "postgresql+asyncpg://u:p@localhost/db",
        ),
    ],
)
def test_sqlalchemy_asyncpg_dsn(raw: str, expected: str) -> None:
    assert sqlalchemy_asyncpg_dsn(raw) == expected
