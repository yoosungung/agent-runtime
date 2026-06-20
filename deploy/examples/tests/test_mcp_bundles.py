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
# mcp_sdk_bundle (tutorial — Naver search + URL fetch)
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


# ────────────────────────────────────────────────────────────────────────────
# search_bundle (production — Naver search + URL fetch)
# ────────────────────────────────────────────────────────────────────────────


class TestSearchBundle:
    async def test_list_tools_exposes_both(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({}, secrets)

        tools = await server.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"naver_search", "fetch_url"}

    async def test_naver_search_dispatches_with_credentials(
        self, monkeypatch, load_bundle, secrets
    ):
        mod = load_bundle("mcp/search_bundle", "search_bundle")

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

        import importlib

        naver_mod = importlib.import_module("providers.naver")
        monkeypatch.setattr(naver_mod.httpx, "AsyncClient", _Client)

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
        assert captured["params"] == {"query": "서울 날씨", "display": 3, "start": 1}
        assert result["query"] == "서울 날씨"
        assert result["category"] == "web"
        assert result["total"] == 2
        assert result["items"][0] == {"title": "날씨 정보", "link": "https://a.example/1"}
        assert result["items"][1] == {"title": "서울 날씨", "link": "https://b.example/2"}

    async def test_naver_search_blog_category(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")

        captured: dict = {}

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "total": 1,
                    "items": [
                        {
                            "title": "<b>맛집</b>",
                            "link": "https://blog.example/1",
                            "description": "리뷰",
                            "bloggername": "foodie",
                            "postdate": "20240101",
                        },
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
                captured["params"] = params
                return _Resp()

        import importlib

        naver_mod = importlib.import_module("providers.naver")
        monkeypatch.setattr(naver_mod.httpx, "AsyncClient", _Client)

        server = mod.build_server(
            {"naver": {"client_id": "id", "client_secret": "sec"}},
            secrets,
        )
        result = await server.dispatch(
            "naver_search",
            {"query": "강남 맛집", "category": "blog", "sort": "date"},
        )

        assert captured["url"] == "https://openapi.naver.com/v1/search/blog.json"
        assert captured["params"]["sort"] == "date"
        assert result["category"] == "blog"
        assert result["items"][0]["description"] == "foodie — 리뷰"
        assert result["items"][0]["pub_date"] == "20240101"

    async def test_naver_search_without_credentials_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(RuntimeError, match="naver credentials missing"):
            await server.dispatch("naver_search", {"query": "test"})

    async def test_fetch_url_truncates_to_8kb(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")

        big = "x" * 20000

        class _Resp:
            text = big
            is_redirect = False
            headers = {"content-type": "text/plain"}

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

        import importlib

        fetch_mod = importlib.import_module("providers.fetch")
        monkeypatch.setattr(fetch_mod.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(
            importlib.import_module("utils"),
            "validate_fetch_url",
            lambda url, **_: url,
        )

        server = mod.build_server({}, secrets)
        result = await server.dispatch("fetch_url", {"url": "https://example.com"})
        assert isinstance(result, str)
        assert len(result) == 8192

    async def test_fetch_url_blocks_ssrf_localhost(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(ValueError, match="blocked"):
            await server.dispatch("fetch_url", {"url": "http://127.0.0.1/"})

    async def test_fetch_url_blocks_ssrf_metadata_ip(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(ValueError, match="blocked"):
            await server.dispatch(
                "fetch_url", {"url": "http://169.254.169.254/latest/meta-data/"}
            )

    async def test_dispatch_unknown_tool_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({}, secrets)
        with pytest.raises(ValueError, match="unknown tool"):
            await server.dispatch("not_a_tool", {})

    async def test_mask_error_details_hides_original_error(self, load_bundle, secrets):
        mod = load_bundle("mcp/search_bundle", "search_bundle")
        server = mod.build_server({"mcp": {"mask_error_details": True}}, secrets)
        with pytest.raises(RuntimeError, match="tool call failed"):
            await server.dispatch("not_a_tool", {})


# ────────────────────────────────────────────────────────────────────────────
# email_bundle (IMAP/POP3/SMTP, Outlook, Gmail)
# ────────────────────────────────────────────────────────────────────────────


def _imap_cfg() -> dict:
    return {
        "mcp": {"mask_error_details": False},
        "email": {
            "provider": "imap",
            "default_folder": "INBOX",
            "page_size": 25,
            "body_max_bytes": 32,
            "from_address": "bot@example.com",
        },
        "imap": {
            "host": "imap.example.com",
            "port": 993,
            "use_ssl": True,
            "username": "bot@example.com",
            "password": "imap-secret",
        },
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "use_starttls": True,
            "username": "bot@example.com",
            "password": "smtp-secret",
        },
    }


class TestEmailBundle:
    async def test_list_tools_exposes_three(self, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        server = mod.build_server(_imap_cfg(), secrets)
        tools = await server.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"list_messages", "read_message", "send_message"}

    async def test_unknown_provider_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        cfg = _imap_cfg()
        cfg["email"]["provider"] = "unknown"
        with pytest.raises(ValueError, match="unsupported email.provider"):
            mod.build_server(cfg, secrets)

    async def test_provider_imap_list_messages(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")

        class _FakeImap:
            def login(self, *_args) -> None:
                return None

            def select(self, *_args, **_kwargs):
                return "OK", [b"1"]

            def uid(self, command, *args):
                if command == "search":
                    return "OK", [b"1 2"]
                if command == "fetch":
                    uid = args[0]
                    headers = (
                        f"From: sender@example.com\r\n"
                        f"To: bot@example.com\r\n"
                        f"Subject: Hello {uid.decode()}\r\n"
                        f"Date: Sat, 20 Jun 2026 09:00:00 +0000\r\n"
                    ).encode()
                    return "OK", [(f"{uid.decode()} (FLAGS (\\Seen))".encode(), headers)]
                return "NO", [b""]

            def logout(self) -> None:
                return None

        monkeypatch.setattr("imaplib.IMAP4_SSL", lambda *a, **k: _FakeImap())

        server = mod.build_server(_imap_cfg(), secrets)
        result = await server.dispatch("list_messages", {"limit": 2})
        assert len(result["messages"]) == 2
        assert result["messages"][0]["from"] == "sender@example.com"
        assert result["messages"][0]["subject"] == "Hello 2"

    async def test_read_message_truncates_body(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        body = "x" * 100

        class _FakeImap:
            def login(self, *_args) -> None:
                return None

            def select(self, *_args, **_kwargs):
                return "OK", [b"1"]

            def uid(self, command, *args):
                if command == "fetch":
                    raw = (
                        "From: sender@example.com\r\n"
                        "To: bot@example.com\r\n"
                        "Subject: Long\r\n"
                        "Date: Sat, 20 Jun 2026 09:00:00 +0000\r\n"
                        "\r\n"
                        f"{body}"
                    ).encode()
                    return "OK", [(b"42 (FLAGS (\\Seen))", raw)]
                return "NO", [b""]

            def logout(self) -> None:
                return None

        monkeypatch.setattr("imaplib.IMAP4_SSL", lambda *a, **k: _FakeImap())

        server = mod.build_server(_imap_cfg(), secrets)
        result = await server.dispatch("read_message", {"message_id": "42"})
        assert result["body_text"] == "x" * 32

    async def test_send_message_smtp(self, monkeypatch, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        import importlib

        imap_mod = importlib.import_module("providers.imap_smtp")
        captured: dict = {}

        def _fake_send(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(imap_mod, "send_via_smtp", _fake_send)

        server = mod.build_server(_imap_cfg(), secrets)
        result = await server.dispatch(
            "send_message",
            {"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        )
        assert captured["to"] == ["user@example.com"]
        assert captured["subject"] == "Hi"
        assert result["status"] == "sent"

    async def test_outlook_without_credentials_raises(self, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        cfg = {
            "email": {"provider": "outlook"},
            "outlook": {"tenant_id": "t", "client_id": "c"},
        }
        server = mod.build_server(cfg, secrets)
        with pytest.raises(RuntimeError, match="outlook credentials missing"):
            await server.dispatch("list_messages", {})

    async def test_outlook_oauth_refresh_uses_merged_token(
        self, monkeypatch, load_bundle, secrets
    ):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        import importlib

        outlook_mod = importlib.import_module("providers.outlook")

        class _FakeApp:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def acquire_token_by_refresh_token(self, refresh_token, scopes):
                assert refresh_token == "user-refresh-token"
                return {"access_token": "graph-token"}

        monkeypatch.setattr(outlook_mod.msal, "ConfidentialClientApplication", _FakeApp)

        captured: dict = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"value": []}

            content = b"{}"

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def request(self, method, url, **kwargs):
                captured["url"] = url
                captured["headers"] = kwargs.get("headers")
                return _Resp()

        monkeypatch.setattr(outlook_mod.httpx, "AsyncClient", _Client)

        cfg = {
            "email": {"provider": "outlook", "default_folder": "INBOX"},
            "outlook": {
                "tenant_id": "tenant",
                "client_id": "client",
                "client_secret": "secret",
                "mailbox": "shared@company.com",
                "auth": "oauth_refresh",
                "refresh_token": "user-refresh-token",
            },
        }
        server = mod.build_server(cfg, secrets)
        await server.dispatch("list_messages", {})
        assert captured["headers"]["Authorization"] == "Bearer graph-token"
        assert "/me/mailFolders/inbox/messages" in captured["url"]

    async def test_mask_error_details(self, load_bundle, secrets):
        mod = load_bundle("mcp/email_bundle", "email_bundle")
        server = mod.build_server({"mcp": {"mask_error_details": True}, "email": {"provider": "imap"}}, secrets)
        with pytest.raises(RuntimeError, match="tool call failed"):
            await server.dispatch("not_a_tool", {})
