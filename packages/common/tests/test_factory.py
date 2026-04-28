"""Unit tests for runtime_common.factory."""

import pytest

from runtime_common.factory import call_factory, merge_configs
from runtime_common.secrets import EnvSecretResolver


class TestMergeConfigs:
    def test_source_only(self):
        assert merge_configs({"a": 1}, None) == {"a": 1}

    def test_user_only(self):
        assert merge_configs({}, {"b": 2}) == {"b": 2}

    def test_both_no_conflict(self):
        assert merge_configs({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_user_wins_on_conflict(self):
        assert merge_configs({"a": 1, "b": 99}, {"a": 42}) == {"a": 42, "b": 99}

    def test_empty_user_dict_returns_source_copy(self):
        src = {"x": 1}
        result = merge_configs(src, {})
        assert result == {"x": 1}
        result["x"] = 99  # mutation must not affect source
        assert src["x"] == 1

    def test_returns_new_dict(self):
        src = {"k": "v"}
        result = merge_configs(src, None)
        assert result is not src

    # ── section-level (1-depth) deep merge ───────────────────────────────────

    def test_section_user_key_does_not_erase_source_sibling(self):
        # user overrides only recursion_limit; checkpointer must survive
        source = {"langgraph": {"recursion_limit": 25, "checkpointer": "postgres"}}
        user = {"langgraph": {"recursion_limit": 200}}
        result = merge_configs(source, user)
        assert result["langgraph"] == {"recursion_limit": 200, "checkpointer": "postgres"}

    def test_section_user_adds_new_key(self):
        source = {"langgraph": {"checkpointer": "memory"}}
        user = {"langgraph": {"model": "anthropic:claude-sonnet-4-6"}}
        result = merge_configs(source, user)
        assert result["langgraph"] == {
            "checkpointer": "memory",
            "model": "anthropic:claude-sonnet-4-6",
        }

    def test_section_user_wins_within_section(self):
        source = {"adk": {"model": "google:gemini-2.0-flash", "temperature": 0.0}}
        user = {"adk": {"model": "anthropic:claude-opus-4-7", "max_llm_calls": 500}}
        result = merge_configs(source, user)
        assert result["adk"] == {
            "model": "anthropic:claude-opus-4-7",
            "temperature": 0.0,
            "max_llm_calls": 500,
        }

    def test_scalar_user_overrides_scalar_source(self):
        source = {"timeout_seconds": 60}
        user = {"timeout_seconds": 120}
        assert merge_configs(source, user) == {"timeout_seconds": 120}

    def test_source_section_not_mutated(self):
        source = {"langgraph": {"recursion_limit": 25}}
        original_section = source["langgraph"]
        merge_configs(source, {"langgraph": {"recursion_limit": 50}})
        assert original_section["recursion_limit"] == 25  # source untouched

    def test_multi_section_independent(self):
        source = {
            "timeout_seconds": 60,
            "langgraph": {"checkpointer": "postgres", "recursion_limit": 100},
            "adk": {"model": "google:gemini-2.0-flash", "temperature": 0.0},
        }
        user = {
            "timeout_seconds": 120,
            "langgraph": {"recursion_limit": 200},
        }
        result = merge_configs(source, user)
        assert result["timeout_seconds"] == 120
        assert result["langgraph"] == {"checkpointer": "postgres", "recursion_limit": 200}
        assert result["adk"] == {"model": "google:gemini-2.0-flash", "temperature": 0.0}


def _secrets():
    return EnvSecretResolver()


def test_zero_arg_factory():
    def factory():
        return "zero-arg"

    result = call_factory(factory, {}, _secrets())
    assert result == "zero-arg"


def test_one_arg_factory():
    def factory(user_cfg):
        return user_cfg.get("key", "default")

    result = call_factory(factory, {"key": "value"}, _secrets())
    assert result == "value"


def test_two_arg_factory():
    received = {}

    def factory(user_cfg, secrets):
        received["cfg"] = user_cfg
        received["secrets"] = secrets
        return "two-arg"

    secrets = _secrets()
    result = call_factory(factory, {"x": 1}, secrets)
    assert result == "two-arg"
    assert received["cfg"] == {"x": 1}
    assert received["secrets"] is secrets


def test_callable_class_zero_arg():
    class MyFactory:
        def __call__(self):
            return "class-zero"

    result = call_factory(MyFactory(), {}, _secrets())
    assert result == "class-zero"


def test_callable_class_two_arg():
    class MyFactory:
        def __call__(self, user_cfg, secrets):
            return user_cfg

    result = call_factory(MyFactory(), {"a": 1}, _secrets())
    assert result == {"a": 1}


def test_bad_signature_raises():
    def factory(a, b, c):
        return "bad"

    with pytest.raises(TypeError, match="unsupported signature"):
        call_factory(factory, {}, _secrets())


def test_optional_args_dispatches_as_zero():
    def factory(user_cfg=None, secrets=None):
        return "optional"

    result = call_factory(factory, {}, _secrets())
    assert result == "optional"
