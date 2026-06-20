"""Tests for infra_meta env helpers."""

import pytest

from runtime_common.config_schema import InfraConfig
from runtime_common.infra_env import (
    infra_config_to_env,
    validate_infra_env_raw,
    validate_infra_secret_keys,
    validate_infra_secrets_input,
)


def test_infra_config_minimal():
    cfg = InfraConfig()
    assert cfg.opik_workspace == "default"
    assert cfg.opik_url is None


def test_infra_config_rejects_unknown_key():
    with pytest.raises(Exception):
        InfraConfig.model_validate({"unknown": "x"})


def test_validate_infra_env_raw():
    out = validate_infra_env_raw({"opik_url": "http://opik:5173/api"})
    assert out["opik_url"] == "http://opik:5173/api"


def test_infra_config_to_env():
    flat = infra_config_to_env(
        {
            "opik_url": "http://opik:5173/api",
            "opik_workspace": "prod",
            "default_llm_model": "openai:gpt-4o-mini",
        }
    )
    assert flat == {
        "OPIK_URL": "http://opik:5173/api",
        "OPIK_WORKSPACE": "prod",
        "DEFAULT_LLM_MODEL": "openai:gpt-4o-mini",
    }


def test_validate_infra_secret_keys_whitelist():
    assert validate_infra_secret_keys(["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]) == [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]


def test_validate_infra_secret_keys_rejects_unknown():
    with pytest.raises(ValueError, match="not allowed"):
        validate_infra_secret_keys(["MY_CUSTOM_KEY"])


def test_validate_infra_secret_keys_rejects_reserved():
    with pytest.raises(ValueError, match="reserved"):
        validate_infra_secret_keys(["POD_NAME"])


def test_validate_infra_secrets_input():
    out = validate_infra_secrets_input({"OPENAI_API_KEY": "sk-test"})
    assert out["OPENAI_API_KEY"] == "sk-test"
