"""Low-level MCP SDK infra providers.

The MCP SDK exposes very few runtime knobs beyond what the bundle declares
in code (tools, resources, prompts, capabilities). The only knob currently
modelled is ``mask_error_details`` — bundles enforce it themselves at call
boundaries since the SDK has no first-class hook.
"""

from __future__ import annotations


def _section(cfg: dict) -> dict:
    return cfg.get("mcp") or {}


def get_mask_error_details(cfg: dict) -> bool:
    return bool(_section(cfg).get("mask_error_details", False))
