"""Path helpers for virtual filesystem backends."""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timezone


def normalize_path(path: str) -> str:
    """Return an absolute VFS path with a leading slash."""
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    # Collapse duplicate slashes (except leading)
    while "//" in path:
        path = path.replace("//", "/")
    return path or "/"


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


def direct_children(paths: list[str], dir_path: str) -> list[dict]:
    """List non-recursive children of ``dir_path`` from flat absolute paths."""
    dir_path = normalize_dir(dir_path)
    prefix = "" if dir_path == "/" else dir_path
    seen: dict[str, dict] = {}

    for raw in paths:
        p = normalize_path(raw)
        if not path_under_dir(p, dir_path):
            continue
        rel = p[len(prefix) :] if prefix else p
        if rel.startswith("/"):
            rel = rel[1:]
        if not rel:
            continue
        parts = rel.split("/")
        name = parts[0]
        child = f"{prefix}/{name}" if prefix else f"/{name}"
        child = normalize_path(child)
        if len(parts) == 1:
            seen[name] = {"path": child, "is_dir": False}
        else:
            seen[name] = {"path": child + "/", "is_dir": True}

    entries = list(seen.values())
    entries.sort(key=lambda e: e["path"])
    return entries


def glob_paths(paths: list[str], pattern: str, base_path: str | None = None) -> list[str]:
    """Return stored paths matching a glob pattern."""
    if base_path:
        base_path = normalize_dir(base_path)
        paths = [p for p in paths if path_under_dir(p, base_path)]
    norm_pattern = normalize_path(pattern)
    matched = []
    for p in paths:
        if fnmatch.fnmatch(normalize_path(p), norm_pattern):
            matched.append(normalize_path(p))
    return sorted(matched)


def grep_paths(
    files: dict[str, str],
    pattern: str,
    path: str | None = None,
    glob_filter: str | None = None,
) -> list[dict]:
    """Search file contents; returns GrepMatch-like dicts."""
    regex = re.compile(re.escape(pattern))
    matches: list[dict] = []
    for file_path, content in sorted(files.items()):
        fp = normalize_path(file_path)
        if path and not path_under_dir(fp, path):
            continue
        if glob_filter and not fnmatch.fnmatch(fp, glob_filter):
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if regex.search(line):
                matches.append({"path": fp, "line": i, "text": line})
    return matches


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
    return datetime.now(timezone.utc).isoformat()
