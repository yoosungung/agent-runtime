"""Tests for runtime_common.providers.adk."""

from unittest.mock import MagicMock

import pytest

from runtime_common.providers.adk import build_session_service, sqlalchemy_asyncpg_dsn


class _MapSecretResolver:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def resolve(self, ref: str) -> str:
        if ref not in self._values:
            raise KeyError(ref)
        return self._values[ref]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@localhost/db",
            "postgresql+asyncpg://u:p@localhost/db",
        ),
        (
            "postgresql://u:p@localhost/db?sslmode=disable",
            "postgresql+asyncpg://u:p@localhost/db",
        ),
        (
            "postgresql+asyncpg://u:p@localhost/db?sslmode=disable",
            "postgresql+asyncpg://u:p@localhost/db",
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


def test_build_session_service_default_is_database(monkeypatch):
    pytest.importorskip("google.adk")
    captured: dict[str, str] = {}

    class FakeDatabaseSessionService:
        def __init__(self, db_url: str) -> None:
            captured["db_url"] = db_url

    monkeypatch.setattr(
        "google.adk.sessions.DatabaseSessionService",
        FakeDatabaseSessionService,
    )

    secrets = _MapSecretResolver({"SESSION_DB_DSN": "postgresql://u:p@localhost/db"})
    build_session_service({}, secrets)

    assert captured["db_url"] == "postgresql+asyncpg://u:p@localhost/db"


def test_build_session_service_memory_opt_out(monkeypatch):
    pytest.importorskip("google.adk")
    fake_memory = MagicMock()
    monkeypatch.setattr(
        "google.adk.sessions.InMemorySessionService",
        lambda: fake_memory,
    )

    secrets = _MapSecretResolver({"SESSION_DB_DSN": "postgresql://u:p@localhost/db"})
    result = build_session_service({"adk": {"session_service": "memory"}}, secrets)

    assert result is fake_memory


def test_adk_get_model_preset(monkeypatch):
    from runtime_common.providers.adk import get_model

    monkeypatch.setenv("LLM_PRESET_MY_GEMINI_MODE", "frontier")
    monkeypatch.setenv("LLM_PRESET_MY_GEMINI_PROVIDER", "google")
    monkeypatch.setenv("LLM_PRESET_MY_GEMINI_MODEL_ID", "gemini-2.5-pro")

    assert get_model({"adk": {"model": "preset:MY_GEMINI"}}) == "google:gemini-2.5-pro"


def test_adk_get_model_default_fallback(monkeypatch):
    from runtime_common.providers.adk import get_model

    monkeypatch.setenv("DEFAULT_LLM_MODEL", "google:gemini-2.0-flash-exp")
    assert get_model({}) == "google:gemini-2.0-flash-exp"

