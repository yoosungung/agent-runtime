"""E2E test fixtures for Envoy + ext-authz integration.

Starts three components per test module:
  1. A mock ext-authz HTTP server (controlled via X-Test-Mode header).
  2. A mock pool HTTP server (records received requests).
  3. An Envoy Docker container wired to talk to both via host.docker.internal.

All expensive fixtures are scoped to "module" so Envoy starts only once per
test file.
"""

from __future__ import annotations

import base64
import json
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Principal JSON that the mock ext-authz includes in x-principal header.
# Matches the shape of runtime_common.schemas.Principal.
# ---------------------------------------------------------------------------
_PRINCIPAL_JSON = json.dumps(
    {
        "sub": "user1",
        "user_id": 1,
        "tenant": None,
        "access": [],
        "grace_applied": False,
        "is_admin": False,
        "must_change_password": False,
    }
)
_PRINCIPAL_B64 = base64.b64encode(_PRINCIPAL_JSON.encode()).decode()

# ---------------------------------------------------------------------------
# Envoy YAML template.  Placeholders: {ext_authz_port}, {pool_port}.
# Mirrors the production config (envoy.yaml) but routes everything to a
# single STRICT_DNS pool cluster so tests can verify Lua rewrites.
# ---------------------------------------------------------------------------
_ENVOY_CONFIG_TEMPLATE = """\
admin:
  address:
    socket_address: {{address: 0.0.0.0, port_value: 9901}}

static_resources:
  listeners:
  - name: listener_0
    address:
      socket_address: {{address: 0.0.0.0, port_value: 8080}}
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          codec_type: AUTO
          stat_prefix: ingress_http
          http_filters:
          - name: envoy.filters.http.ext_authz
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
              http_service:
                server_uri:
                  uri: http://host.docker.internal:{ext_authz_port}
                  cluster: ext_authz_cluster
                  timeout: 5s
                authorization_request:
                  allowed_headers:
                    patterns:
                    - exact: authorization
                    - exact: content-type
                    - exact: content-length
                    - prefix: x-
                  with_request_body:
                    max_request_bytes: 8192
                    allow_partial_message: false
                authorization_response:
                  allowed_upstream_headers:
                    patterns:
                    - exact: x-pod-addr
                    - exact: x-principal
                    - exact: x-source-checksum
                    - exact: x-source-version
                    - exact: x-grace-applied
              failure_mode_allow: false
          - name: envoy.filters.http.lua
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.lua.v3.Lua
              default_source_code:
                inline_string: |
                  function envoy_on_request(handle)
                    local pod_addr = handle:headers():get("x-pod-addr")
                    if pod_addr and pod_addr ~= "" then
                      handle:headers():replace(":authority", pod_addr)
                      handle:headers():replace(":path", "/invoke")
                      handle:headers():remove("x-pod-addr")
                    end
                  end
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
          route_config:
            name: local_route
            virtual_hosts:
            - name: backend
              domains: ["*"]
              routes:
              - match: {{prefix: /}}
                route:
                  cluster: pool_cluster
                  timeout: 10s

  clusters:
  - name: ext_authz_cluster
    type: STRICT_DNS
    connect_timeout: 2s
    load_assignment:
      cluster_name: ext_authz_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: host.docker.internal
                port_value: {ext_authz_port}

  - name: pool_cluster
    type: STRICT_DNS
    connect_timeout: 2s
    load_assignment:
      cluster_name: pool_cluster
      endpoints:
      - lb_endpoints:
        - endpoint:
            address:
              socket_address:
                address: host.docker.internal
                port_value: {pool_port}
"""


def _free_port() -> int:
    """Return an available TCP port on the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Mock ext-authz server
# ---------------------------------------------------------------------------


class _ExtAuthzState:
    """Thread-safe container for the last request seen by the mock ext-authz."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_request: dict[str, Any] | None = None
        self.pool_port: int = 0  # filled in by fixture before server starts

    def record(self, method: str, path: str, headers: dict[str, str], body: bytes) -> None:
        with self._lock:
            self.last_request = {
                "method": method,
                "path": path,
                "headers": headers,
                "body": body,
            }

    def get_last(self) -> dict[str, Any] | None:
        with self._lock:
            return self.last_request

    def clear(self) -> None:
        with self._lock:
            self.last_request = None


def _make_ext_authz_handler(state: _ExtAuthzState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # silence request logs
            pass

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            hdrs = {k.lower(): v for k, v in self.headers.items()}

            state.record(self.command, self.path, hdrs, body)

            mode = hdrs.get("x-test-mode", "allow")

            if mode == "deny":
                self._respond(403, {"detail": "access denied"})
            elif mode == "deny-401":
                self._respond(401, {"detail": "unauthorized"})
            else:
                # allow — return the headers that Envoy copies onto the upstream request.
                pod_addr = f"host.docker.internal:{state.pool_port}"
                resp_headers = {
                    "x-pod-addr": pod_addr,
                    "x-principal": _PRINCIPAL_B64,
                    "x-source-checksum": "sha256:abc123",
                    "x-source-version": "v1",
                }
                self._respond(200, body=None, extra_headers=resp_headers)

        def _respond(
            self,
            code: int,
            body: dict[str, Any] | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            payload = json.dumps(body).encode() if body is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if payload:
                self.wfile.write(payload)

    return _Handler


# ---------------------------------------------------------------------------
# Mock pool server
# ---------------------------------------------------------------------------


class _PoolState:
    """Thread-safe container for requests received by the mock pool."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.received: list[dict[str, Any]] = []

    def record(self, method: str, path: str, headers: dict[str, str], body: bytes) -> None:
        with self._lock:
            self.received.append(
                {
                    "method": method,
                    "path": path,
                    "headers": headers,
                    "body": body,
                }
            )

    def get_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.received)

    def clear(self) -> None:
        with self._lock:
            self.received.clear()


def _make_pool_handler(state: _PoolState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802
            self._handle()

        def do_GET(self) -> None:  # noqa: N802
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            state.record(self.command, self.path, hdrs, body)

            payload = json.dumps({"result": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return _Handler


def _start_server(
    handler_class: type[BaseHTTPRequestHandler],
    port: int,
) -> HTTPServer:
    """Start an HTTPServer on the given port in a daemon thread."""
    server = HTTPServer(("0.0.0.0", port), handler_class)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mock_ext_authz() -> tuple[int, _ExtAuthzState]:
    """Start mock ext-authz HTTP server. Returns (port, state)."""
    state = _ExtAuthzState()
    port = _free_port()
    handler = _make_ext_authz_handler(state)
    server = _start_server(handler, port)
    yield port, state
    server.shutdown()


@pytest.fixture(scope="module")
def mock_pool() -> tuple[int, _PoolState]:
    """Start mock pool HTTP server. Returns (port, state)."""
    state = _PoolState()
    port = _free_port()
    handler = _make_pool_handler(state)
    server = _start_server(handler, port)
    yield port, state
    server.shutdown()


@pytest.fixture(scope="module")
def envoy(
    mock_ext_authz: tuple[int, _ExtAuthzState], mock_pool: tuple[int, _PoolState]
) -> httpx.Client:
    """Start an Envoy Docker container and return an httpx.Client pointed at it.

    Skips the entire module if Docker is not available.
    """
    ext_authz_port, ext_authz_state = mock_ext_authz
    pool_port, _pool_state = mock_pool

    # Tell the ext-authz mock which pool port to advertise in x-pod-addr.
    ext_authz_state.pool_port = pool_port

    # Skip if testcontainers / Docker unavailable.
    try:
        import docker
        from testcontainers.core.container import DockerContainer

        docker.from_env().ping()
    except Exception as exc:
        pytest.skip(f"Docker unavailable, skipping e2e tests: {exc}")

    from testcontainers.core.container import DockerContainer

    # Write Envoy config to a temp file that persists for the module lifetime.
    config_yaml = _ENVOY_CONFIG_TEMPLATE.format(
        ext_authz_port=ext_authz_port,
        pool_port=pool_port,
    )

    tmp_dir = tempfile.mkdtemp()
    config_path = Path(tmp_dir) / "envoy.yaml"
    config_path.write_text(config_yaml)

    container = DockerContainer(image="envoyproxy/envoy:v1.31-latest")
    container.with_command("-c /etc/envoy/envoy.yaml --log-level warn")
    container.with_volume_mapping(str(config_path), "/etc/envoy/envoy.yaml", "ro")
    container.with_exposed_ports(8080, 9901)

    # On Linux, Docker containers cannot reach the host via host.docker.internal
    # without an explicit host gateway mapping.
    if sys.platform != "darwin":
        container.with_kwargs(extra_hosts={"host.docker.internal": "host-gateway"})

    try:
        container.start()
    except Exception as exc:
        pytest.skip(f"Failed to start Envoy container: {exc}")

    # Wait until Envoy's admin endpoint is ready.
    admin_port = int(container.get_exposed_port(9901))
    envoy_port = int(container.get_exposed_port(8080))

    _wait_for_admin(admin_port, timeout=30)

    client = httpx.Client(
        base_url=f"http://127.0.0.1:{envoy_port}",
        timeout=10.0,
    )

    yield client

    client.close()
    container.stop()


def _wait_for_admin(port: int, timeout: float = 30.0) -> None:
    """Poll Envoy's admin /ready endpoint until it responds 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}/ready", timeout=1.0)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Envoy admin endpoint on port {port} not ready after {timeout}s")
