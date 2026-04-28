"""Tests for the mcp-base example bundles."""

from __future__ import annotations

import pytest


@pytest.fixture
def secrets():
    from runtime_common.secrets import EnvSecretResolver

    return EnvSecretResolver()


def _unwrap(structured: object) -> object:
    """FastMCP wraps non-dict tool returns under {'result': ...}."""
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    return structured


# ────────────────────────────────────────────────────────────────────────────
# fastmcp_bundle (calculator + fetch_url)
# ────────────────────────────────────────────────────────────────────────────


class TestFastmcpBundle:
    def test_factory_returns_fastmcp(self, load_bundle, secrets):
        from fastmcp import FastMCP

        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")
        server = mod.build_server({}, secrets)
        assert isinstance(server, FastMCP)

    async def test_calculate_basic_arithmetic(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")
        server = mod.build_server({}, secrets)

        result = await server.call_tool("calculate", {"expression": "(3 + 4) * 2 ** 3"})
        assert _unwrap(result.structured_content) == 56.0

    async def test_calculate_rejects_names(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(Exception, match="could not evaluate"):
            await server.call_tool("calculate", {"expression": "__import__('os')"})

    async def test_calculate_rejects_zero_div(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(Exception, match="could not evaluate"):
            await server.call_tool("calculate", {"expression": "1/0"})

    async def test_fetch_url_calls_httpx(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")

        captured: dict = {}

        class _Resp:
            text = "hello world"

            def raise_for_status(self) -> None:
                return None

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                captured["init"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def get(self, url):
                captured["url"] = url
                return _Resp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

        server = mod.build_server({}, secrets)
        result = await server.call_tool("fetch_url", {"url": "http://example.com"})
        assert captured["url"] == "http://example.com"
        text = "".join(getattr(p, "text", "") for p in (result.content or []))
        assert "hello world" in text

    def test_server_kwargs_applied(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/fastmcp_bundle", "fastmcp_bundle")
        cfg = {"fastmcp": {"strict_input_validation": True, "mask_error_details": True}}
        server = mod.build_server(cfg, secrets)
        assert server._mask_error_details is True
        assert server.strict_input_validation is True


# ────────────────────────────────────────────────────────────────────────────
# mcp_sdk_bundle (Naver search + URL fetch — keys via source_meta.config)
# ────────────────────────────────────────────────────────────────────────────


class TestMcpSdkBundle:
    async def test_list_tools_exposes_both(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")
        server = mod.build_server({}, secrets)

        tools = await server.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"naver_search", "fetch_url"}

    async def test_naver_search_dispatches_with_credentials(
        self, monkeypatch, load_bundle, secrets
    ):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")

        captured: dict = {}

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "total": 2,
                    "items": [
                        {"title": "<b>날씨</b> 정보", "link": "https://a.example/1"},
                        {"title": "서울 <b>날씨</b>", "link": "https://b.example/2"},
                    ],
                }

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def get(self, url, *, headers, params):
                captured["url"] = url
                captured["headers"] = headers
                captured["params"] = params
                return _Resp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

        server = mod.build_server(
            {"naver": {"client_id": "id-123", "client_secret": "sec-456"}},
            secrets,
        )
        result = await server.dispatch("naver_search", {"query": "서울 날씨", "display": 3})

        assert captured["url"] == "https://openapi.naver.com/v1/search/webkr.json"
        assert captured["headers"] == {
            "X-Naver-Client-Id": "id-123",
            "X-Naver-Client-Secret": "sec-456",
        }
        assert captured["params"] == {"query": "서울 날씨", "display": 3}
        # Tags stripped, items normalized.
        assert result["query"] == "서울 날씨"
        assert result["total"] == 2
        assert result["items"][0] == {"title": "날씨 정보", "link": "https://a.example/1"}
        assert result["items"][1] == {"title": "서울 날씨", "link": "https://b.example/2"}

    async def test_naver_search_without_credentials_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(RuntimeError, match="naver credentials missing"):
            await server.dispatch("naver_search", {"query": "test"})

    async def test_fetch_url_truncates_to_8kb(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")

        big = "x" * 20000

        class _Resp:
            text = big

            def raise_for_status(self) -> None:
                return None

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def get(self, url):
                return _Resp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)

        server = mod.build_server({}, secrets)
        result = await server.dispatch("fetch_url", {"url": "https://example.com"})
        assert isinstance(result, str)
        assert len(result) == 8192

    async def test_dispatch_unknown_tool_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(ValueError, match="unknown tool"):
            await server.dispatch("not_a_tool", {})

    async def test_mask_error_details_hides_original_error(self, load_bundle, secrets):
        mod = load_bundle("mcp-base/mcp_sdk_bundle", "mcp_sdk_bundle")
        server = mod.build_server({"mcp": {"mask_error_details": True}}, secrets)
        with pytest.raises(RuntimeError, match="tool call failed"):
            await server.dispatch("not_a_tool", {})
