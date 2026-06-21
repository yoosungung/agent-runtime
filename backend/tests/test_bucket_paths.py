from __future__ import annotations

import pytest

from backend.bucket_paths import (
    InvalidBucketPathError,
    join_prefix,
    normalize_key,
    normalize_prefix,
    sha256_from_key,
)


def test_normalize_prefix_root():
    assert normalize_prefix("") == ""
    assert normalize_prefix("imports") == "imports/"


def test_normalize_prefix_rejects_traversal():
    with pytest.raises(InvalidBucketPathError):
        normalize_prefix("../etc")


def test_normalize_prefix_blocks_tmp():
    with pytest.raises(InvalidBucketPathError):
        normalize_prefix("tmp/")


def test_normalize_key_file():
    assert normalize_key("abc.zip") == "abc.zip"


def test_normalize_key_rejects_absolute():
    with pytest.raises(InvalidBucketPathError):
        normalize_key("/etc/passwd")


def test_sha256_from_key():
    hex64 = "a" * 64
    assert sha256_from_key(f"{hex64}.zip") == hex64
    assert sha256_from_key(f"imports/{hex64}.sig") == hex64
    assert sha256_from_key("notes.txt") is None


def test_join_prefix():
    assert join_prefix("imports/", "foo.zip") == "imports/foo.zip"
    assert join_prefix("", "foo.zip") == "foo.zip"
