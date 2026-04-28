"""E2E integration tests: real Envoy container + mock ext-authz + mock pool.

These tests verify:
  * The Envoy → ext-authz HTTP contract (body buffering, header forwarding,
    allow/deny behaviour).
  * The Lua filter rewrites :path to /invoke and removes x-pod-addr.

Skip marker: ``pytest.mark.e2e`` — requires a running Docker daemon.
All tests in this module are automatically skipped when Docker is unavailable
because the ``envoy`` fixture calls ``pytest.skip`` in that case.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

# Attempt to import testcontainers — if it is not installed the entire module
# is skipped gracefully rather than failing with ImportError.
testcontainers = pytest.importorskip("testcontainers", reason="testcontainers not installed")

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke_request(
    client: httpx.Client,
    *,
    body: dict[str, Any] | None = None,
    token: str = "Bearer test-token",
    test_mode: str = "allow",
    path: str = "/v1/agents/invoke",
) -> httpx.Response:
    """Send a POST request through Envoy, setting X-Test-Mode for the mock."""
    if body is None:
        body = {"agent": "chat-bot", "input": "hello"}
    return client.post(
        path,
        content=json.dumps(body),
        headers={
            "Authorization": token,
            "Content-Type": "application/json",
            "X-Test-Mode": test_mode,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_allow_agent_invoke(envoy: httpx.Client, mock_pool: tuple, mock_ext_authz: tuple) -> None:
    """Allow path: ext-authz returns 200 → Envoy routes to pool → pool sees request."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, test_mode="allow")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    # Pool must have received at least one request.
    received = pool_state.get_all()
    assert len(received) >= 1, "Mock pool received no requests"


@pytest.mark.e2e
def test_deny_forbidden(envoy: httpx.Client, mock_pool: tuple, mock_ext_authz: tuple) -> None:
    """Deny path (403): ext-authz returns 403 → Envoy returns 403 to client, pool not called."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, test_mode="deny")

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    # Pool should NOT have been reached.
    received = pool_state.get_all()
    assert len(received) == 0, f"Pool should not receive denied requests, got: {received}"


@pytest.mark.e2e
def test_deny_unauthorized(envoy: httpx.Client, mock_pool: tuple, mock_ext_authz: tuple) -> None:
    """Deny path (401): ext-authz returns 401 → Envoy returns 401 to client."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, test_mode="deny-401")

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    received = pool_state.get_all()
    assert len(received) == 0, f"Pool should not receive unauthorized requests, got: {received}"


@pytest.mark.e2e
def test_ext_authz_receives_body(envoy: httpx.Client, mock_ext_authz: tuple) -> None:
    """Verify Envoy buffers the request body and forwards it to ext-authz."""
    _, authz_state = mock_ext_authz
    authz_state.clear()

    body = {"agent": "chat-bot", "input": "hello world"}
    _invoke_request(envoy, body=body, test_mode="allow")

    last = authz_state.get_last()
    assert last is not None, "ext-authz received no request"

    # The body forwarded to ext-authz must contain the original JSON payload.
    received_body = last["body"]
    assert received_body, (
        "ext-authz received an empty body — Envoy body buffering may be misconfigured"
    )

    parsed = json.loads(received_body)
    assert parsed.get("agent") == "chat-bot", f"Unexpected body: {parsed}"
    assert parsed.get("input") == "hello world", f"Unexpected body: {parsed}"


@pytest.mark.e2e
def test_ext_authz_receives_authorization_header(
    envoy: httpx.Client, mock_ext_authz: tuple
) -> None:
    """Verify Envoy forwards the Authorization header to ext-authz."""
    _, authz_state = mock_ext_authz
    authz_state.clear()

    _invoke_request(envoy, token="Bearer super-secret-token", test_mode="allow")

    last = authz_state.get_last()
    assert last is not None, "ext-authz received no request"

    auth_value = last["headers"].get("authorization", "")
    assert auth_value == "Bearer super-secret-token", (
        f"Authorization header not forwarded correctly. Got: {auth_value!r}"
    )


@pytest.mark.e2e
def test_pool_receives_rewritten_path(envoy: httpx.Client, mock_pool: tuple) -> None:
    """Verify the Lua filter rewrites :path to /invoke before reaching the pool."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, path="/v1/agents/invoke", test_mode="allow")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    received = pool_state.get_all()
    assert len(received) >= 1, "Pool received no requests"

    # The Lua filter must have rewritten the original /v1/agents/invoke to /invoke.
    paths = [r["path"] for r in received]
    assert "/invoke" in paths, (
        f"Lua filter did not rewrite path to /invoke. Pool saw paths: {paths}"
    )


@pytest.mark.e2e
def test_ext_authz_receives_x_test_mode_header(envoy: httpx.Client, mock_ext_authz: tuple) -> None:
    """Verify x-* headers (with prefix: x-) are forwarded to ext-authz by Envoy."""
    _, authz_state = mock_ext_authz
    authz_state.clear()

    _invoke_request(envoy, test_mode="allow")

    last = authz_state.get_last()
    assert last is not None, "ext-authz received no request"

    # x-test-mode must be present — it matches the `prefix: x-` allowed_headers rule.
    mode_value = last["headers"].get("x-test-mode", "")
    assert mode_value == "allow", f"x-test-mode header not forwarded by Envoy. Got: {mode_value!r}"


@pytest.mark.e2e
def test_pool_does_not_receive_x_pod_addr(envoy: httpx.Client, mock_pool: tuple) -> None:
    """Verify the Lua filter removes x-pod-addr before forwarding to the pool."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, test_mode="allow")
    assert resp.status_code == 200

    received = pool_state.get_all()
    assert len(received) >= 1, "Pool received no requests"

    # x-pod-addr must have been removed by the Lua filter.
    for req in received:
        assert "x-pod-addr" not in req["headers"], (
            f"Lua filter should have removed x-pod-addr before forwarding to pool. "
            f"Headers: {req['headers']}"
        )


@pytest.mark.e2e
def test_pool_receives_principal_header(envoy: httpx.Client, mock_pool: tuple) -> None:
    """Verify Envoy copies x-principal from the ext-authz allow response to the pool request."""
    _, pool_state = mock_pool
    pool_state.clear()

    resp = _invoke_request(envoy, test_mode="allow")
    assert resp.status_code == 200

    received = pool_state.get_all()
    assert len(received) >= 1, "Pool received no requests"

    last_req = received[-1]
    assert "x-principal" in last_req["headers"], (
        f"x-principal header not forwarded to pool. Headers: {last_req['headers']}"
    )
