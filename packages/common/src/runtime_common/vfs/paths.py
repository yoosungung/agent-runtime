"""Path helpers for virtual filesystem backends."""

from __future__ import annotations

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
