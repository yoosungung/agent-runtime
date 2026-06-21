from __future__ import annotations

import pytest
import pytest_asyncio
from starlette.datastructures import UploadFile

from backend.object_store_browser import LocalObjectStoreBrowser


@pytest_asyncio.fixture
async def browser(tmp_path):
    root = tmp_path / "storage"
    root.mkdir()
    (root / "tmp").mkdir()
    b = LocalObjectStoreBrowser(str(root))
    yield b, root


@pytest.mark.asyncio
async def test_local_list_hides_tmp(browser):
    b, root = browser
    (root / "hello.txt").write_text("hi")
    result = await b.list_objects("")
    names = [item.name for item in result.items]
    assert "hello.txt" in names
    assert "tmp" not in names


@pytest.mark.asyncio
async def test_local_create_folder_and_upload(browser):
    b, root = browser
    key = await b.create_folder("", "imports")
    assert key == "imports/"
    assert (root / "imports").is_dir()

    upload = UploadFile(filename="note.txt", file=__import__("io").BytesIO(b"data"))
    uploaded_key = await b.upload("imports/", upload, max_bytes=1024)
    assert uploaded_key == "imports/note.txt"
    assert (root / "imports" / "note.txt").read_bytes() == b"data"


@pytest.mark.asyncio
async def test_local_move_rename(browser):
    b, root = browser
    (root / "old.txt").write_text("x")
    dest_keys = await b.move(["old.txt"], "new.txt")
    assert dest_keys == ["new.txt"]
    assert not (root / "old.txt").exists()
    assert (root / "new.txt").exists()


@pytest.mark.asyncio
async def test_local_delete_folder_recursive(browser):
    b, root = browser
    folder = root / "archive"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    await b.delete_keys(["archive/"])
    assert not folder.exists()
