"""App /invoke integration tests — VFS pull/lock/push (TDD)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from hermes_base.app import app
from hermes_base.profile_lock import MemoryProfileLock
from hermes_base.profile_materializer import profile_home
from hermes_base.vfs_profile import ProfileVfsSync, vfs_path
from runtime_common.schemas import Principal, ResolveResponse, SourceMeta, UserMeta
from runtime_common.vfs.store import MemoryAgentVfsStore


def _sample_cfg() -> dict:
    return {
        "hermes": {
            "soul": "You are a test assistant.",
            "model": "openai/gpt-4o",
            "mcp_servers": ["mcp-a"],
            "mcp_tools": [{"server": "mcp-a", "name": "tool_a", "description": "t"}],
            "skills": ["plan"],
            "max_iterations": 10,
        }
    }


def _principal_b64() -> str:
    p = Principal(sub="u1", user_id=42)
    return base64.b64encode(p.model_dump_json().encode()).decode()


def _resolved() -> ResolveResponse:
    return ResolveResponse(
        source=SourceMeta(
            kind="agent",
            name="my-bot",
            version="v1",
            runtime_pool="agent:hermes",
            deploy_mode="hermes_general",
            config=_sample_cfg(),
        ),
        user=UserMeta(
            principal_id="42",
            config={},
            secrets_ref=None,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


@pytest.fixture()
def client(mock_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = MemoryAgentVfsStore()
    profile_lock = MemoryProfileLock(ttl_sec=60)
    monkeypatch.setenv("HERMES_WORK_DIR", str(tmp_path))

    async def fake_open_vfs(settings):
        return store, None

    async def fake_resolve(*args, **kwargs):
        return _resolved()

    monkeypatch.setattr("hermes_base.app._open_vfs_store", fake_open_vfs)
    monkeypatch.setattr("hermes_base.app.resolve_for_invoke", fake_resolve)

    with TestClient(app) as c:
        c.app.state.profile_lock = profile_lock
        c.app.state.agent_factory = mock_agent_factory
        c.app.state.vfs_sync = ProfileVfsSync(store)
        yield c, store, profile_lock, tmp_path


@pytest.fixture()
def mock_agent_factory():
    def factory(**kwargs: object) -> MagicMock:
        mock = MagicMock()
        mock.run_conversation = MagicMock(return_value={"final_response": "hello from hermes"})
        return mock

    return factory


def test_invoke_pull_run_push(client) -> None:
    c, store, _, tmp_path = client
    resp = c.post(
        "/invoke",
        json={
            "agent": "my-bot",
            "input": {"message": "hi"},
            "session_id": "sess-1",
        },
        headers={"x-principal": _principal_b64()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["output"] == "hello from hermes"
    assert body["result"]["agent"] == "my-bot"
    assert profile_home(tmp_path, "my-bot").is_dir()


@pytest.mark.asyncio()
async def test_invoke_pushes_memory_changes(client) -> None:
    c, store, _, tmp_path = client

    def factory_with_memory(**kwargs: object) -> MagicMock:
        mock = MagicMock()

        def run_conversation(**kw: object) -> dict:
            scratch = profile_home(tmp_path, "my-bot")
            mem = scratch / "memories"
            mem.mkdir(parents=True, exist_ok=True)
            (mem / "MEMORY.md").write_text("# fact\n", encoding="utf-8")
            return {"final_response": "done"}

        mock.run_conversation = MagicMock(side_effect=run_conversation)
        return mock

    c.app.state.agent_factory = factory_with_memory
    resp = c.post(
        "/invoke",
        json={"agent": "my-bot", "input": {"message": "remember"}},
        headers={"x-principal": _principal_b64()},
    )
    assert resp.status_code == 200

    record = await store.read("agent", "my-bot", vfs_path("memories/MEMORY.md"))
    assert record is not None
    assert "fact" in record.content


def test_invoke_lock_contention_returns_429(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _, _ = client

    class Locked(MemoryProfileLock):
        async def try_acquire(self, agent_name: str):
            return None

    c.app.state.profile_lock = Locked(ttl_sec=60)
    resp = c.post(
        "/invoke",
        json={"agent": "my-bot", "input": {"message": "blocked"}},
        headers={"x-principal": _principal_b64()},
    )
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") is not None


def test_invoke_rejects_non_hermes_deploy_mode(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _, _ = client

    async def bad_resolve(*args, **kwargs):
        r = _resolved()
        return ResolveResponse(
            source=r.source.model_copy(update={"deploy_mode": "general"}),
            user=r.user,
        )

    monkeypatch.setattr("hermes_base.app.resolve_for_invoke", bad_resolve)
    resp = c.post(
        "/invoke",
        json={"agent": "my-bot", "input": {"message": "x"}},
        headers={"x-principal": _principal_b64()},
    )
    assert resp.status_code == 400
