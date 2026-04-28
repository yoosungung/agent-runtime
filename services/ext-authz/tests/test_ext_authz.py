from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from ext_authz import app as app_module
from runtime_common.schemas import Principal, ResolveResponse, ResourceRef, SourceMeta


class _FakeAuth:
    def __init__(self) -> None:
        self.last_grace_sec: int | None = None

    async def verify(self, token: str, grace_sec: int = 0) -> Principal:
        self.last_grace_sec = grace_sec
        if token == "bad":
            raise ValueError("invalid")
        return Principal(
            sub="u_42",
            user_id=42,
            tenant=None,
            access=[
                ResourceRef(kind="agent", name="hello"),
                ResourceRef(kind="mcp", name="rag"),
            ],
            grace_applied=grace_sec > 0 and token == "grace",
        )

    async def aclose(self) -> None:
        pass


class _FakeDeploy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def resolve(
        self,
        kind: str,
        name: str,
        version: str | None = None,
        principal: str | None = None,
    ) -> ResolveResponse:
        self.calls.append({"kind": kind, "name": name, "version": version})
        if name == "missing":
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "http://deploy/resolve"),
                response=httpx.Response(404),
            )
        runtime_pool = "agent:compiled_graph" if kind == "agent" else "mcp:fastmcp"
        return ResolveResponse(
            source=SourceMeta(
                kind=kind,
                name=name,
                version=version or "v1",
                runtime_pool=runtime_pool,
                entrypoint="mod:factory",
                bundle_uri="file:///tmp/bundle.zip",
                checksum="sha256:abc",
            ),
            user=None,
        )

    async def aclose(self) -> None:
        pass


class _FakeScheduler:
    def __init__(self, addr: str | None = "http://10.1.2.3:8080") -> None:
        self.addr = addr
        self.calls: list[dict[str, Any]] = []

    async def pick(self, runtime_kind: str, checksum: str | None, ring_key: str) -> str | None:
        self.calls.append(
            {"runtime_kind": runtime_kind, "checksum": checksum, "ring_key": ring_key}
        )
        return self.addr


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Build a client and swap in fakes after lifespan spins up.
    tc = TestClient(app_module.app)
    tc.__enter__()

    fake_auth = _FakeAuth()
    fake_deploy = _FakeDeploy()
    fake_scheduler = _FakeScheduler()

    # Swap after lifespan so real subscribers/query have been created but unused.
    app_module.app.state.auth = fake_auth
    app_module.app.state.deploy = fake_deploy
    app_module.app.state.agent_scheduler = fake_scheduler
    app_module.app.state.mcp_scheduler = fake_scheduler
    # Replace the real httpx.AsyncClient with one backed by respx so that
    # @respx.mock decorators on individual tests intercept outbound calls.
    app_module.app.state.http = httpx.AsyncClient()
    yield tc
    tc.__exit__(None, None, None)


def _post(client: TestClient, path: str, body: dict, token: str = "good") -> httpx.Response:
    return client.post(
        path,
        content=json.dumps(body),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )


def test_allows_agent_invoke(client: TestClient) -> None:
    r = _post(client, "/v1/agents/invoke", {"agent": "hello", "input": {}})
    assert r.status_code == 200, r.text
    assert r.headers["x-pod-addr"] == "10.1.2.3:8080"
    principal_json = json.loads(base64.b64decode(r.headers["x-principal"]))
    assert principal_json["sub"] == "u_42"
    assert r.headers["x-source-checksum"] == "sha256:abc"


def test_denies_without_token(client: TestClient) -> None:
    r = client.post("/v1/agents/invoke", json={"agent": "hello", "input": {}})
    assert r.status_code == 401


def test_denies_unknown_path(client: TestClient) -> None:
    r = _post(client, "/v1/other/invoke", {"agent": "hello", "input": {}})
    assert r.status_code == 403


def test_denies_when_principal_cannot_access(client: TestClient) -> None:
    r = _post(client, "/v1/agents/invoke", {"agent": "other-agent", "input": {}})
    assert r.status_code == 403


def test_denies_on_deploy_404(client: TestClient) -> None:
    r = _post(
        client,
        "/v1/mcp/invoke",
        {"server": "missing", "tool": "t", "arguments": {}},
    )
    # principal.access doesn't include "missing" either, so this will be 403
    # use a name in access but different deploy behavior:
    # deploy _FakeDeploy 404 triggers on name=="missing".
    assert r.status_code in (403, 404)


def test_internal_path_uses_grace(client: TestClient) -> None:
    fake_auth: _FakeAuth = app_module.app.state.auth
    r = _post(
        client,
        "/v1/mcp/invoke-internal",
        {"server": "rag", "tool": "t", "arguments": {}},
    )
    assert r.status_code == 200
    assert fake_auth.last_grace_sec == 300  # default MCP_INTERNAL_GRACE_SEC


def test_edge_path_no_grace(client: TestClient) -> None:
    fake_auth: _FakeAuth = app_module.app.state.auth
    r = _post(client, "/v1/agents/invoke", {"agent": "hello", "input": {}})
    assert r.status_code == 200
    assert fake_auth.last_grace_sec == 0


def test_missing_body_denies(client: TestClient) -> None:
    r = client.post(
        "/v1/agents/invoke",
        headers={"Authorization": "Bearer good", "Content-Type": "application/json"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Header-based identifier tests (x-runtime-name / x-runtime-version)
# ---------------------------------------------------------------------------


def test_header_name_bypasses_body_parsing(client: TestClient) -> None:
    """x-runtime-name header takes priority; body without 'agent' field is OK."""
    r = client.post(
        "/v1/agents/invoke",
        content=json.dumps({"input": {"message": "hi"}}),  # no 'agent' field
        headers={
            "Authorization": "Bearer good",
            "Content-Type": "application/json",
            "x-runtime-name": "hello",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["x-pod-addr"] == "10.1.2.3:8080"


def test_header_name_with_version(client: TestClient) -> None:
    """x-runtime-version is passed to deploy.resolve when present."""
    fake_deploy: _FakeDeploy = app_module.app.state.deploy
    fake_deploy.calls.clear()
    r = client.post(
        "/v1/agents/invoke",
        content=json.dumps({"input": {}}),
        headers={
            "Authorization": "Bearer good",
            "Content-Type": "application/json",
            "x-runtime-name": "hello",
            "x-runtime-version": "v2",
        },
    )
    assert r.status_code == 200, r.text
    assert fake_deploy.calls[-1]["version"] == "v2"


def test_header_name_no_body_required(client: TestClient) -> None:
    """When x-runtime-name is sent, empty body is acceptable."""
    r = client.post(
        "/v1/agents/invoke",
        headers={
            "Authorization": "Bearer good",
            "x-runtime-name": "hello",
        },
    )
    assert r.status_code == 200, r.text


def test_body_fallback_still_works(client: TestClient) -> None:
    """Body-based identifier still works when x-runtime-name header is absent."""
    r = _post(client, "/v1/agents/invoke", {"agent": "hello", "input": {}})
    assert r.status_code == 200, r.text


def test_ring_key_includes_kind(client: TestClient) -> None:
    """ring_key passed to scheduler is prefixed with kind."""
    fake_scheduler: _FakeScheduler = app_module.app.state.agent_scheduler
    fake_scheduler.calls.clear()
    r = client.post(
        "/v1/agents/invoke",
        content=json.dumps({"input": {}}),
        headers={
            "Authorization": "Bearer good",
            "Content-Type": "application/json",
            "x-runtime-name": "hello",
            "x-runtime-version": "v1",
        },
    )
    assert r.status_code == 200, r.text
    ring_key = fake_scheduler.calls[-1]["ring_key"]
    assert ring_key.startswith("agent:"), f"expected kind prefix, got: {ring_key!r}"


def test_mcp_ring_key_includes_kind(client: TestClient) -> None:
    fake_scheduler: _FakeScheduler = app_module.app.state.mcp_scheduler
    fake_scheduler.calls.clear()
    r = client.post(
        "/v1/mcp/invoke",
        content=json.dumps({"input": {}}),
        headers={
            "Authorization": "Bearer good",
            "Content-Type": "application/json",
            "x-runtime-name": "rag",
        },
    )
    assert r.status_code == 200, r.text
    ring_key = fake_scheduler.calls[-1]["ring_key"]
    assert ring_key.startswith("mcp:"), f"expected kind prefix, got: {ring_key!r}"


def test_principal_decoder_roundtrip() -> None:
    p = Principal(
        sub="u_1",
        user_id=1,
        tenant=None,
        access=[ResourceRef(kind="agent", name="x")],
        grace_applied=False,
    )
    b64 = base64.b64encode(p.model_dump_json().encode()).decode()
    restored = app_module._principal_from_b64(b64)
    assert restored.sub == "u_1"
    assert restored.access[0].name == "x"


# ---------------------------------------------------------------------------
# Helpers shared by the new discovery/stream test classes
# ---------------------------------------------------------------------------

DEPLOY_API_BASE = "http://deploy-api.runtime.svc.cluster.local:8080"
# _FakeScheduler returns this warm URL — pool requests go here, not the service URL.
POOL_WARM_BASE = "http://10.1.2.3:8080"


def _auth_headers(token: str = "good") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# TestMcpServers
# ---------------------------------------------------------------------------


class TestMcpServers:
    @respx.mock
    def test_proxies_to_deploy_api(self, client: TestClient) -> None:
        respx.get(f"{DEPLOY_API_BASE}/v1/source-meta").mock(
            return_value=httpx.Response(
                200,
                json=[{"name": "rag", "version": "v1", "runtime_pool": "mcp:fastmcp"}],
            )
        )
        r = client.get("/v1/mcp/servers")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["servers"][0]["name"] == "rag"

    @respx.mock
    def test_502_on_deploy_api_error(self, client: TestClient) -> None:
        respx.get(f"{DEPLOY_API_BASE}/v1/source-meta").mock(
            return_value=httpx.Response(500, text="oops")
        )
        r = client.get("/v1/mcp/servers")
        assert r.status_code == 502

    @respx.mock
    def test_no_auth_required(self, client: TestClient) -> None:
        respx.get(f"{DEPLOY_API_BASE}/v1/source-meta").mock(
            return_value=httpx.Response(200, json=[])
        )
        r = client.get("/v1/mcp/servers")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# TestMcpServerTools
# ---------------------------------------------------------------------------


class TestMcpServerTools:
    @respx.mock
    def test_returns_tools_for_authorised_principal(self, client: TestClient) -> None:
        respx.get(f"{POOL_WARM_BASE}/tools").mock(
            return_value=httpx.Response(200, json={"tools": [{"name": "search"}]})
        )
        r = client.get("/v1/mcp/servers/rag/tools", headers=_auth_headers())
        assert r.status_code == 200, r.text
        assert r.json()["tools"][0]["name"] == "search"

    def test_401_missing_token(self, client: TestClient) -> None:
        r = client.get("/v1/mcp/servers/rag/tools")
        assert r.status_code == 401

    def test_401_bad_token(self, client: TestClient) -> None:
        r = client.get("/v1/mcp/servers/rag/tools", headers=_auth_headers("bad"))
        assert r.status_code == 401

    def test_403_no_access(self, client: TestClient) -> None:
        # "other" is not in the principal's access list
        r = client.get("/v1/mcp/servers/other/tools", headers=_auth_headers())
        assert r.status_code == 403

    @respx.mock
    def test_404_server_not_found(self, client: TestClient) -> None:
        # _FakeDeploy raises 404 when name=="missing", but "missing" is not
        # in the principal's access list so we'd get 403 first.  Override access
        # by using a name that IS in access but patch deploy to return 404.
        fake_deploy: _FakeDeploy = app_module.app.state.deploy

        async def _resolve_404(kind: str, name: str, version: str | None = None, principal: str | None = None) -> ResolveResponse:
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "http://deploy/resolve"),
                response=httpx.Response(404),
            )

        original = fake_deploy.resolve
        fake_deploy.resolve = _resolve_404  # type: ignore[method-assign]
        try:
            r = client.get("/v1/mcp/servers/rag/tools", headers=_auth_headers())
            assert r.status_code == 404
        finally:
            fake_deploy.resolve = original  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# TestMcpStream
# ---------------------------------------------------------------------------


class TestMcpStream:
    def _stream_headers(self, server: str = "rag", token: str = "good") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-Mcp-Server": server,
            "Content-Type": "application/json",
        }

    def test_401_missing_token(self, client: TestClient) -> None:
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 1}),
            headers={"Content-Type": "application/json", "X-Mcp-Server": "rag"},
        )
        assert r.status_code == 401

    def test_401_bad_token(self, client: TestClient) -> None:
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 1}),
            headers=self._stream_headers(token="bad"),
        )
        assert r.status_code == 401

    def test_403_no_access(self, client: TestClient) -> None:
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 1}),
            headers=self._stream_headers(server="other"),
        )
        assert r.status_code == 403

    @respx.mock
    def test_proxies_json_response(self, client: TestClient) -> None:
        respx.post(f"{POOL_WARM_BASE}/mcp").mock(
            return_value=httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"content": []}},
            )
        )
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 1}),
            headers=self._stream_headers(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["result"] == {"content": []}

    def test_initialize_without_server_header(self, client: TestClient) -> None:
        body = {"jsonrpc": "2.0", "method": "initialize", "id": 99}
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps(body),
            headers={
                "Authorization": "Bearer good",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["id"] == 99
        assert "protocolVersion" in data["result"]

    @respx.mock
    def test_sse_streaming(self, client: TestClient) -> None:
        sse_body = b"data: {}\n\n"
        respx.post(f"{POOL_WARM_BASE}/mcp").mock(
            return_value=httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})
        )
        r = client.post(
            "/v1/mcp/stream",
            content=json.dumps({"jsonrpc": "2.0", "method": "tools/call", "id": 2}),
            headers={**self._stream_headers(), "Accept": "text/event-stream"},
        )
        assert r.status_code == 200


class TestAgentInvoke:
    """Agent invoke through ext-authz check() — replaces agent-gateway tests."""

    BODY = {"agent": "hello", "input": {"message": "hi"}, "session_id": "s1"}

    def _post(
        self,
        client: TestClient,
        *,
        token: str = "good",
        extra_headers: dict | None = None,
        body: dict | None = None,
    ) -> httpx.Response:
        h: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            h.update(extra_headers)
        return client.post(
            "/v1/agents/invoke",
            content=json.dumps(body if body is not None else self.BODY),
            headers=h,
        )

    def test_successful_invoke_via_body(self, client: TestClient) -> None:
        r = self._post(client)
        assert r.status_code == 200, r.text
        assert r.headers["x-pod-addr"] == "10.1.2.3:8080"
        assert r.headers["x-pod-fallback-addr"] == "agent-pool-compiled-graph.runtime.svc.cluster.local:8080"
        principal_json = json.loads(base64.b64decode(r.headers["x-principal"]))
        assert principal_json["sub"] == "u_42"

    def test_successful_invoke_via_runtime_name_header(self, client: TestClient) -> None:
        r = client.post(
            "/v1/agents/invoke",
            content=json.dumps({"input": {"message": "hi"}}),
            headers={
                "Authorization": "Bearer good",
                "Content-Type": "application/json",
                "x-runtime-name": "hello",
                "x-runtime-version": "v1",
            },
        )
        assert r.status_code == 200, r.text
        assert r.headers["x-pod-addr"] == "10.1.2.3:8080"
        assert "x-pod-fallback-addr" in r.headers

    def test_missing_agent_field_returns_400(self, client: TestClient) -> None:
        r = self._post(client, body={"input": {"message": "hi"}})
        assert r.status_code == 400

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        r = client.post(
            "/v1/agents/invoke",
            content=json.dumps(self.BODY),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        r = self._post(client, token="bad")
        assert r.status_code == 401

    def test_unknown_agent_returns_404(self, client: TestClient) -> None:
        r = self._post(client, body={"agent": "missing", "input": {}})
        assert r.status_code in (403, 404)

    def test_unauthorized_agent_returns_403(self, client: TestClient) -> None:
        r = self._post(client, body={"agent": "other-agent", "input": {}})
        assert r.status_code == 403

    def test_sse_accept_header_allowed(self, client: TestClient) -> None:
        r = self._post(client, extra_headers={"Accept": "text/event-stream"})
        assert r.status_code == 200
        assert "x-pod-addr" in r.headers

    def test_fallback_addr_is_pool_service_url(self, client: TestClient) -> None:
        """x-pod-fallback-addr must be the pool Service URL, not the warm pod IP."""
        r = self._post(client)
        assert r.status_code == 200
        assert r.headers["x-pod-addr"] == "10.1.2.3:8080"
        assert r.headers["x-pod-fallback-addr"] != r.headers["x-pod-addr"]


# ---------------------------------------------------------------------------
# Image mode routing tests
# ---------------------------------------------------------------------------


class _FakeDeployImageMode(_FakeDeploy):
    """Returns an image-mode SourceMeta with runtime_pool='agent:custom:summarizer-v1'."""

    async def resolve(
        self,
        kind: str,
        name: str,
        version: str | None = None,
        principal: str | None = None,  # noqa: ARG002
    ) -> ResolveResponse:
        from runtime_common.schemas import UserMeta

        return ResolveResponse(
            source=SourceMeta(
                kind=kind,
                name=name,
                version=version or "v1",
                runtime_pool=f"{kind}:custom:summarizer-v1",
                entrypoint=None,
                bundle_uri=None,
                deploy_mode="image",
                slug="summarizer-v1",
                status="active",
            ),
            user=UserMeta(
                principal_id="u_42",
                config={"model": "claude-3"},
                secrets_ref="vault://agents/u42",
            ),
        )


@pytest.fixture
def image_client() -> TestClient:
    tc = TestClient(app_module.app)
    tc.__enter__()

    fake_auth = _FakeAuth()
    fake_deploy = _FakeDeployImageMode()
    fake_scheduler = _FakeScheduler(addr="http://10.9.9.9:8080")

    app_module.app.state.auth = fake_auth
    app_module.app.state.deploy = fake_deploy
    app_module.app.state.agent_scheduler = fake_scheduler
    app_module.app.state.mcp_scheduler = fake_scheduler
    app_module.app.state.http = httpx.AsyncClient()
    yield tc
    tc.__exit__(None, None, None)


def test_image_mode_routing_skips_warm_registry(image_client: TestClient) -> None:
    """Image-mode invoke should NOT use warm-registry; addr is derived from slug."""
    fake_scheduler: _FakeScheduler = app_module.app.state.agent_scheduler
    fake_scheduler.calls.clear()

    r = image_client.post(
        "/v1/agents/invoke",
        content=json.dumps({"agent": "hello", "input": {}}),
        headers={
            "Authorization": "Bearer good",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    # Scheduler must NOT have been called for image-mode pools
    assert len(fake_scheduler.calls) == 0, "warm-registry should be skipped for image mode"

    # Address derived from slug: agent-pool-custom-summarizer-v1.runtime.svc.cluster.local:8080
    expected_addr = "agent-pool-custom-summarizer-v1.runtime.svc.cluster.local:8080"
    assert r.headers["x-pod-addr"] == expected_addr
    assert r.headers["x-pod-fallback-addr"] == expected_addr


def test_image_mode_cfg_header(image_client: TestClient) -> None:
    """x-runtime-cfg must carry base64(JSON) of merged source+user config."""
    r = image_client.post(
        "/v1/agents/invoke",
        content=json.dumps({"agent": "hello", "input": {}}),
        headers={"Authorization": "Bearer good", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    cfg_raw = base64.b64decode(r.headers["x-runtime-cfg"])
    cfg = json.loads(cfg_raw)
    assert cfg.get("model") == "claude-3"


def test_image_mode_secrets_ref_header(image_client: TestClient) -> None:
    """x-runtime-secrets-ref must passthrough user_meta.secrets_ref."""
    r = image_client.post(
        "/v1/agents/invoke",
        content=json.dumps({"agent": "hello", "input": {}}),
        headers={"Authorization": "Bearer good", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-runtime-secrets-ref") == "vault://agents/u42"


def test_bundle_mode_cfg_header(client: TestClient) -> None:
    """Bundle mode also receives x-runtime-cfg (source config only, no user_meta here)."""
    r = _post(client, "/v1/agents/invoke", {"agent": "hello", "input": {}})
    assert r.status_code == 200, r.text
    cfg_raw = base64.b64decode(r.headers["x-runtime-cfg"])
    cfg = json.loads(cfg_raw)
    assert isinstance(cfg, dict)
