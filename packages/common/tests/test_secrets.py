"""Unit tests for runtime_common.secrets."""

import pytest

from runtime_common.secrets import EnvSecretResolver, SecretResolver


def test_env_resolver_found(monkeypatch):
    monkeypatch.setenv("MY_SECRET_KEY", "super-secret")
    resolver = EnvSecretResolver()
    assert resolver.resolve("MY_SECRET_KEY") == "super-secret"


def test_env_resolver_missing(monkeypatch):
    monkeypatch.delenv("DEFINITELY_NOT_SET_12345", raising=False)
    resolver = EnvSecretResolver()
    with pytest.raises(KeyError, match="DEFINITELY_NOT_SET_12345"):
        resolver.resolve("DEFINITELY_NOT_SET_12345")


def test_env_resolver_implements_protocol():
    assert isinstance(EnvSecretResolver(), SecretResolver)


def test_protocol_structural():
    class CustomResolver:
        def resolve(self, ref: str) -> str:
            return f"resolved:{ref}"

    assert isinstance(CustomResolver(), SecretResolver)
