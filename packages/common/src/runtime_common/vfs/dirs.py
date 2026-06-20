"""Directory row materialization for VFS stores."""

from __future__ import annotations

from runtime_common.vfs.paths import normalize_dir, normalize_path, vfs_entry_metadata


def ancestor_dir_paths(parent_path: str) -> list[str]:
    """Return directory paths from ``parent_path`` up to (but excluding) root.

    ``parent_path`` is the parent of a file or nested dir, e.g. ``/foo/bar/`` for
    ``/foo/bar/b.txt``. Root ``/`` is not included — it is implicit.
    """
    current = normalize_dir(parent_path)
    dirs: list[str] = []
    while current != "/":
        dirs.append(current)
        trimmed = current.rstrip("/")
        if "/" not in trimmed[1:]:
            current = "/"
            break
        parent, _ = trimmed.rsplit("/", 1)
        current = normalize_dir(parent)
    return dirs


def dir_row_fields(dir_path: str) -> tuple[str, str, str, int]:
    """Return (path, parent_path, name, size) for a materialized directory row."""
    norm = normalize_dir(dir_path)
    parent_path, name, size = vfs_entry_metadata(norm, b"", is_dir=True)
    return norm, parent_path, name, size


def file_parent_path(file_path: str) -> str:
    """Parent directory path for a file path."""
    norm = normalize_path(file_path)
    parent_path, _, _ = vfs_entry_metadata(norm, b"")
    return parent_path
