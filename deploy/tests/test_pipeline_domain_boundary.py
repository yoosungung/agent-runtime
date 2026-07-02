"""Import boundary: backend/agent-base must not import path_graph internals directly."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCAN_ROOTS = (
    REPO_ROOT / "backend/src/backend",
    REPO_ROOT / "runtimes/agent-base/src/agent_base",
)

_ALLOWLIST_PARTS = (
    "backend/pipeline_domain/",
)

_FORBIDDEN_PREFIXES = (
    "path_graph.admin",
    "path_graph.contracts",
    "path_graph.config",
    "path_graph.meta",
    "path_graph.storage",
    "path_graph.rag",
)


def _is_allowlisted(path: Path) -> bool:
    posix = path.as_posix()
    return any(part in posix for part in _ALLOWLIST_PARTS)


def _forbidden_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            name = alias.name
            if any(name == p or name.startswith(p + ".") for p in _FORBIDDEN_PREFIXES):
                return name
    if isinstance(node, ast.ImportFrom) and node.module:
        mod = node.module
        if any(mod == p or mod.startswith(p + ".") for p in _FORBIDDEN_PREFIXES):
            return mod
    return None


def _scan_file(path: Path) -> list[str]:
    if _is_allowlisted(path):
        return []
    tree = ast.parse(path.read_text(), filename=str(path))
    rel = path.relative_to(REPO_ROOT).as_posix()
    violations: list[str] = []
    for node in ast.walk(tree):
        mod = _forbidden_module(node)
        if mod:
            violations.append(f"{rel}: forbidden import {mod}")
    return violations


def test_pipeline_domain_import_boundary() -> None:
    violations: list[str] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            violations.extend(_scan_file(path))
    assert not violations, "\n".join(violations)


def test_pipeline_domain_imports_console_only() -> None:
    domain_init = REPO_ROOT / "backend/src/backend/pipeline_domain/__init__.py"
    tree = ast.parse(domain_init.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module == "path_graph.console", (
                f"pipeline_domain must import path_graph.console only, got {node.module}"
            )
