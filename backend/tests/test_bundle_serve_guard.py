"""Unit tests for bundle_serve_guard helpers."""

from __future__ import annotations

from backend.bundle_serve_guard import bundle_serve_blocked_by_proxy


def test_bundle_serve_blocked_by_proxy_detects_forwarded_for() -> None:
    scope = {
        "type": "http",
        "path": "/bundles/abc.zip",
        "headers": [(b"x-forwarded-for", b"203.0.113.1")],
    }
    assert bundle_serve_blocked_by_proxy(scope) is True


def test_bundle_serve_blocked_by_proxy_allows_direct_cluster_fetch() -> None:
    scope = {
        "type": "http",
        "path": "/bundles/abc.zip",
        "headers": [],
    }
    assert bundle_serve_blocked_by_proxy(scope) is False


def test_bundle_serve_blocked_by_proxy_ignores_non_bundle_paths() -> None:
    scope = {
        "type": "http",
        "path": "/api/source-meta",
        "headers": [(b"x-forwarded-for", b"203.0.113.1")],
    }
    assert bundle_serve_blocked_by_proxy(scope) is False
