"""Tests for WikiS3ReadBackend."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from runtime_common.vfs.wiki_backend import WikiS3ReadBackend


class _NoSuchKey(Exception):
    pass


@pytest.fixture()
def s3_client():
    client = MagicMock()
    client.exceptions.NoSuchKey = _NoSuchKey
    return client


@pytest.mark.asyncio
async def test_wiki_s3_aread_returns_file_data(s3_client):
    body = MagicMock()
    body.read.return_value = b"# Title\n\nBody"
    s3_client.get_object.return_value = {"Body": body}

    backend = WikiS3ReadBackend(
        bucket="runtime-bundles",
        prefix="wiki/dev/p1/",
        s3_client=s3_client,
    )
    result = await backend.aread("page.md")

    assert result.error is None
    assert result.file_data is not None
    assert "# Title" in result.file_data["content"]
    assert result.file_data["encoding"] == "utf-8"


@pytest.mark.asyncio
async def test_wiki_s3_aread_missing_file(s3_client):
    s3_client.get_object.side_effect = _NoSuchKey()

    backend = WikiS3ReadBackend(
        bucket="runtime-bundles",
        prefix="wiki/dev/p1/",
        s3_client=s3_client,
    )
    result = await backend.aread("missing.md")

    assert result.file_data is None
    assert "not found" in (result.error or "")
