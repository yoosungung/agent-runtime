from __future__ import annotations

import re
from pathlib import PurePosixPath

BLOCKED_LOCAL_PREFIXES = ("tmp/", "tmp")

_SHA256_SUFFIX_RE = re.compile(r"^([a-f0-9]{64})\.(zip|sig)$")


class InvalidBucketPathError(ValueError):
    """Raised when a bucket key or prefix is invalid or escapes the storage root."""


def normalize_prefix(prefix: str) -> str:
    """Normalize a directory prefix (may be empty for root)."""
    if prefix is None:
        prefix = ""
    prefix = prefix.strip()
    if prefix.startswith("/"):
        raise InvalidBucketPathError("Absolute paths are not allowed")
    if prefix and not prefix.endswith("/"):
        prefix = f"{prefix}/"
    _validate_relative_path(prefix, allow_trailing_slash=True)
    if prefix in ("tmp/", BLOCKED_LOCAL_PREFIXES):
        raise InvalidBucketPathError("Access to tmp/ is not allowed")
    if prefix.startswith("tmp/"):
        raise InvalidBucketPathError("Access to tmp/ is not allowed")
    return prefix


def normalize_key(key: str) -> str:
    """Normalize a file or folder key relative to storage root."""
    if key is None:
        raise InvalidBucketPathError("Key is required")
    key = key.strip()
    if key.startswith("/"):
        raise InvalidBucketPathError("Absolute paths are not allowed")
    is_folder = key.endswith("/")
    _validate_relative_path(key, allow_trailing_slash=True)
    if key in BLOCKED_LOCAL_PREFIXES or key == "tmp/":
        raise InvalidBucketPathError("Access to tmp/ is not allowed")
    if key.startswith("tmp/"):
        raise InvalidBucketPathError("Access to tmp/ is not allowed")
    if is_folder and not key.endswith("/"):
        key = f"{key}/"
    return key


def join_prefix(prefix: str, name: str) -> str:
    parent = normalize_prefix(prefix)
    clean_name = name.strip().strip("/")
    if not clean_name or clean_name in (".", ".."):
        raise InvalidBucketPathError("Invalid folder or file name")
    if "/" in clean_name or "\\" in clean_name:
        raise InvalidBucketPathError("Name must not contain path separators")
    return f"{parent}{clean_name}"


def basename(key: str) -> str:
    normalized = normalize_key(key) if key.endswith("/") else key.strip().lstrip("/")
    path = PurePosixPath(normalized.rstrip("/"))
    return path.name


def sha256_from_key(key: str) -> str | None:
    """Extract sha256 hex from bundle object keys like `{hex}.zip` or `path/{hex}.sig`."""
    name = basename(key)
    match = _SHA256_SUFFIX_RE.match(name)
    if match is None:
        return None
    return match.group(1)


def _validate_relative_path(path: str, *, allow_trailing_slash: bool) -> None:
    if "\x00" in path:
        raise InvalidBucketPathError("Invalid path")
    if not path:
        return
    parts = PurePosixPath(path.rstrip("/") if allow_trailing_slash and path.endswith("/") else path).parts
    if ".." in parts:
        raise InvalidBucketPathError("Path traversal is not allowed")
    if PurePosixPath(path).is_absolute():
        raise InvalidBucketPathError("Absolute paths are not allowed")
