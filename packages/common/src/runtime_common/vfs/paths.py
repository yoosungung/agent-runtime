"""Path helpers for virtual filesystem backends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def normalize_path(path: str) -> str:
    """Return an absolute VFS path with a leading slash."""
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    # Collapse duplicate slashes (except leading)
    while "//" in path:
        path = path.replace("//", "/")
    return path or "/"


def vfs_entry_metadata(path: str, content: bytes, *, is_dir: bool = False) -> tuple[str, str, int]:
    """Return (parent_path, name, size) for a VFS row."""
    norm = normalize_path(path)
    trimmed = norm.rstrip("/")
    if trimmed == "" or trimmed == "/":
        return "/", "", 0
    if "/" in trimmed[1:]:
        parent, name = trimmed.rsplit("/", 1)
        parent_path = parent + "/"
    else:
        parent_path, name = "/", trimmed.lstrip("/")
    size = 0 if is_dir else len(content)
    return parent_path, name, size


def normalize_dir(path: str) -> str:
    """Normalize a directory path; root stays ``/``, others end with ``/``."""
    path = normalize_path(path)
    if path == "/":
        return "/"
    return path.rstrip("/") + "/"


def path_under_dir(file_path: str, dir_path: str) -> bool:
    """Return True if ``file_path`` is under ``dir_path`` (inclusive)."""
    file_path = normalize_path(file_path)
    dir_path = normalize_dir(dir_path)
    if dir_path == "/":
        return True
    return file_path == dir_path.rstrip("/") or file_path.startswith(dir_path)


def path_like_prefix(path: str | None) -> str | None:
    """Return a SQL LIKE prefix for scoping glob/grep under a directory."""
    if path is None:
        return None
    norm = normalize_dir(path)
    if norm == "/":
        return None
    return norm


def glob_to_pg_regex(pattern: str) -> str:
    """Translate a fnmatch-style glob (absolute VFS path) to a Postgres regex."""
    pattern = normalize_path(pattern)
    parts: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                parts.append(".*")
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
            else:
                parts.append(".*")
                i += 1
        elif ch == "?":
            parts.append(".")
            i += 1
        elif ch in ".^$+{}[]|()\\":
            parts.append("\\" + ch)
            i += 1
        else:
            parts.append(ch)
            i += 1
    parts.append("$")
    return "".join(parts)


@dataclass(frozen=True)
class GlobSqlPlan:
    """Index-friendly decomposition of a VFS glob pattern."""

    path_exact: str | None = None
    path_prefix: str | None = None
    name_exact: str | None = None
    name_like: str | None = None
    regex: str = ""
    use_regex: bool = False


def _literal_path_prefix(dir_part: str) -> str | None:
    if not dir_part or dir_part == "/":
        return None
    i = 0
    while i < len(dir_part):
        ch = dir_part[i]
        if ch == "*" and i + 1 < len(dir_part) and dir_part[i + 1] == "*":
            prefix = dir_part[:i]
            if not prefix or prefix == "/":
                return None
            return prefix if prefix.endswith("/") else prefix + "/"
        if ch in "*?":
            return None
        i += 1
    return dir_part


def _basename_to_like(base_part: str) -> str | None:
    if "**" in base_part:
        return None
    return base_part.replace("*", "%").replace("?", "_")


def _dir_has_non_recursive_wildcard(dir_part: str) -> bool:
    if dir_part in ("/**/", "/**", "/"):
        return False
    if not any(ch in dir_part for ch in "*?"):
        return False
    return _literal_path_prefix(dir_part) is None


def plan_glob_sql(pattern: str) -> GlobSqlPlan:
    """Decompose a glob into btree / pg_trgm friendly predicates when possible."""
    pattern = normalize_path(pattern)
    regex = glob_to_pg_regex(pattern)

    if "*" not in pattern and "?" not in pattern:
        return GlobSqlPlan(path_exact=pattern, regex=regex, use_regex=False)

    slash = pattern.rfind("/")
    if slash < 0:
        dir_part, base_part = "/", pattern
    else:
        dir_part = pattern[: slash + 1]
        base_part = pattern[slash + 1 :]

    path_prefix = _literal_path_prefix(dir_part)
    if _dir_has_non_recursive_wildcard(dir_part):
        return GlobSqlPlan(regex=regex, use_regex=True)

    if base_part in ("", "**"):
        return _ensure_glob_predicate(
            GlobSqlPlan(path_prefix=path_prefix, regex=regex, use_regex=False),
            regex,
        )

    if base_part == "*":
        return GlobSqlPlan(path_prefix=path_prefix, regex=regex, use_regex=True)

    if "*" not in base_part and "?" not in base_part:
        return GlobSqlPlan(
            path_prefix=path_prefix,
            name_exact=base_part,
            regex=regex,
            use_regex=False,
        )

    name_like = _basename_to_like(base_part)
    if name_like is None:
        return GlobSqlPlan(path_prefix=path_prefix, regex=regex, use_regex=True)

    plan = GlobSqlPlan(
        path_prefix=path_prefix,
        name_like=name_like,
        regex=regex,
        use_regex=False,
    )
    return _ensure_glob_predicate(plan, regex)


def _ensure_glob_predicate(plan: GlobSqlPlan, regex: str) -> GlobSqlPlan:
    if (
        plan.path_exact is None
        and plan.path_prefix is None
        and plan.name_exact is None
        and plan.name_like is None
        and not plan.use_regex
    ):
        return GlobSqlPlan(regex=regex, use_regex=True)
    return plan


def merge_glob_scope_prefix(base_path: str | None, plan: GlobSqlPlan) -> str | None:
    """Combine aglob directory scope with a pattern literal prefix."""
    scope = path_like_prefix(base_path)
    pattern_prefix = plan.path_prefix
    if scope is None:
        return pattern_prefix
    if pattern_prefix is None:
        return scope
    if pattern_prefix.startswith(scope):
        return pattern_prefix
    return scope


def format_read_content(content: str, offset: int = 0, limit: int = 2000) -> str:
    """Format content with line numbers (cat -n style)."""
    lines = content.splitlines()
    start = max(0, offset)
    end = start + limit if limit > 0 else len(lines)
    selected = lines[start:end]
    width = len(str(start + len(selected)))
    numbered = []
    for idx, line in enumerate(selected, start=start + 1):
        numbered.append(f"{idx:>{width}}\t{line}")
    return "\n".join(numbered)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
