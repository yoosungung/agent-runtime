"""Tests for infra_meta env helpers."""

import pytest

from runtime_common.infra_env import (
    merge_infra_env,
    normalize_stored_env,
    validate_infra_env_patch,
    validate_infra_secret_keys,
    validate_infra_secrets_input,
)


def test_normalize_stored_env_flat():
    assert normalize_stored_env({"OPIK_URL": "http://opik/api"}) == {
        "OPIK_URL": "http://opik/api"
    }


def test_normalize_stored_env_legacy_snake_case():
    assert normalize_stored_env({"opik_url": "http://opik/api", "opik_workspace": "dev"}) == {
        "OPIK_URL": "http://opik/api",
        "OPIK_WORKSPACE": "dev",
    }


def test_validate_infra_env_patch_accepts_custom_key():
    out = validate_infra_env_patch({"MY_PLATFORM_FLAG": "1", "OPIK_URL": "http://x"})
    assert out == {"MY_PLATFORM_FLAG": "1", "OPIK_URL": "http://x"}


def test_validate_infra_env_patch_rejects_lowercase():
    with pytest.raises(ValueError, match="must match"):
        validate_infra_env_patch({"opik_url": "x"})


def test_validate_infra_env_patch_rejects_reserved():
    with pytest.raises(ValueError, match="reserved"):
        validate_infra_env_patch({"POD_NAME": "x"})


def test_merge_infra_env_preserves_extra_keys():
    merged = merge_infra_env(
        {"OPIK_URL": "old", "CUSTOM_VAR": "keep"},
        {"OPIK_URL": "new"},
    )
    assert merged == {"OPIK_URL": "new", "CUSTOM_VAR": "keep"}


def test_merge_infra_env_removes_on_empty_string():
    merged = merge_infra_env({"OPIK_URL": "x", "CUSTOM_VAR": "y"}, {"OPIK_URL": ""})
    assert merged == {"CUSTOM_VAR": "y"}


def test_validate_infra_secret_keys_accepts_custom():
    assert validate_infra_secret_keys(["OPENAI_API_KEY", "MY_VENDOR_API_KEY"]) == [
        "OPENAI_API_KEY",
        "MY_VENDOR_API_KEY",
    ]


def test_validate_infra_secrets_input():
    out = validate_infra_secrets_input({"OPENAI_API_KEY": "sk-test", "MY_KEY": "v"})
    assert out["OPENAI_API_KEY"] == "sk-test"
