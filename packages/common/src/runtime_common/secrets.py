from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvSecretResolver:
    """Resolves secret references from environment variables.

    ref format: the env var name, e.g. "MY_API_KEY".
    """

    def resolve(self, ref: str) -> str:
        value = os.environ.get(ref)
        if value is None:
            raise KeyError(f"secret env var not found: {ref!r}")
        return value


class VaultSecretResolver:
    """Resolves secrets from HashiCorp Vault (placeholder — implement with hvac)."""

    def __init__(self, vault_addr: str, token: str) -> None:
        self._addr = vault_addr
        self._token = token

    def resolve(self, ref: str) -> str:
        raise NotImplementedError("VaultSecretResolver not yet implemented")


class AwsSecretsManagerResolver:
    """Resolves secrets from AWS Secrets Manager (placeholder — implement with boto3)."""

    def __init__(self, region: str) -> None:
        self._region = region

    def resolve(self, ref: str) -> str:
        raise NotImplementedError("AwsSecretsManagerResolver not yet implemented")
