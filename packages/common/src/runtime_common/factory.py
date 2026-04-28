"""Factory invocation helpers.

call_factory: Inspects the factory signature and dispatches to the right call shape:
- zero-arg: factory()
- one-arg (user_cfg): factory(user_cfg)
- two-arg (user_cfg, secrets): factory(user_cfg, secrets)

merge_configs: 1-depth section-aware merge of source and user configs (user wins).
Top-level dict values (config sections like "langgraph", "adk") are merged key-by-key
so a user override of one section key does not erase sibling keys from source.
Scalar values and nested dicts beyond 1 level are replaced wholesale by the user value.
"""

from __future__ import annotations

import inspect
from typing import Any

from runtime_common.secrets import SecretResolver


def merge_configs(source_cfg: dict, user_cfg: dict | None) -> dict:
    """1-depth section-aware merge. User keys override source keys.

    If both source and user have the same top-level key and both values are dicts
    (i.e. a config section), the dicts are merged shallowly so user section keys
    override source section keys without discarding unrelated source keys.

    Returns a new dict; source_cfg and user_cfg are not mutated.
    """
    merged = dict(source_cfg)
    if user_cfg:
        for key, user_val in user_cfg.items():
            source_val = merged.get(key)
            if isinstance(source_val, dict) and isinstance(user_val, dict):
                merged[key] = {**source_val, **user_val}
            else:
                merged[key] = user_val
    return merged


def call_factory(factory: Any, user_cfg: dict, secrets: SecretResolver) -> Any:
    try:
        sig = inspect.signature(factory)
    except (ValueError, TypeError):
        return factory()

    params = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    n_required = len(params)
    n_total = len(sig.parameters)

    if n_total == 0:
        return factory()
    elif n_required <= 1 and n_total >= 1:
        return factory(user_cfg)
    elif n_required <= 2 and n_total >= 2:
        return factory(user_cfg, secrets)
    else:
        raise TypeError(
            f"factory {factory!r} has unsupported signature: "
            "expected zero-arg, (user_cfg,), or (user_cfg, secrets)"
        )
