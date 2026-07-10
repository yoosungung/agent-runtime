"""Shared Postgres glob query builder for VFS tables."""

from __future__ import annotations

from typing import Any

from runtime_common.vfs.paths import GlobSqlPlan, merge_glob_scope_prefix, plan_glob_sql


def glob_path_filter_sql(
    pattern: str,
    base_path: str | None,
    *,
    start_param: int,
) -> tuple[str, list[Any], int]:
    """Return SQL AND-clauses, bind values, and the next parameter index."""
    plan = plan_glob_sql(pattern)
    clauses: list[str] = []
    params: list[Any] = []
    idx = start_param

    if plan.path_exact is not None:
        clauses.append(f"path = ${idx}")
        params.append(plan.path_exact)
        return " AND ".join(clauses), params, idx + 1

    prefix = merge_glob_scope_prefix(base_path, plan)
    if prefix is not None:
        clauses.append(f"path LIKE ${idx} || '%'")
        params.append(prefix)
        idx += 1

    if plan.name_exact is not None:
        clauses.append(f"name = ${idx}")
        params.append(plan.name_exact)
        idx += 1
    elif plan.name_like is not None:
        clauses.append(f"name LIKE ${idx}")
        params.append(plan.name_like)
        idx += 1

    if plan.use_regex:
        clauses.append(f"path ~ ${idx}")
        params.append(plan.regex)
        idx += 1

    return " AND ".join(clauses), params, idx
