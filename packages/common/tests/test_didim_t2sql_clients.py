"""Unit tests for DidimRagClient and T2SqlClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from runtime_common.didim_client import TOOL_EMBED, TOOL_SEARCH, DidimRagClient
from runtime_common.t2sql_client import TOOL_EXPLAIN, TOOL_QUERY, TOOL_SCHEMA, T2SqlClient

BASE_DIDIM = "http://didim-rag-svc"
BASE_T2SQL = "http://t2sql-svc"


# ---------------------------------------------------------------------------
# DidimRagClient
# ---------------------------------------------------------------------------


class TestDidimRagClient:
    async def test_call_search_posts_to_tool_path(self):
        with respx.mock(base_url=BASE_DIDIM) as mock:
            mock.post("/search").mock(
                return_value=httpx.Response(200, json={"hits": [{"id": "1", "score": 0.9}]})
            )
            client = DidimRagClient(base_url=BASE_DIDIM)
            result = await client.call(TOOL_SEARCH, {"query": "LLM agents"})
            assert result == {"hits": [{"id": "1", "score": 0.9}]}
            assert mock.calls.call_count == 1

    async def test_call_injects_default_collection(self):
        with respx.mock(base_url=BASE_DIDIM) as mock:
            route = mock.post("/search").mock(return_value=httpx.Response(200, json={}))
            client = DidimRagClient(base_url=BASE_DIDIM, collection="my-col")
            await client.call(TOOL_SEARCH, {"query": "test"})
            body = route.calls[0].request.read()
            import json

            payload = json.loads(body)
            assert payload["collection"] == "my-col"

    async def test_call_collection_in_args_takes_precedence(self):
        with respx.mock(base_url=BASE_DIDIM) as mock:
            route = mock.post("/search").mock(return_value=httpx.Response(200, json={}))
            client = DidimRagClient(base_url=BASE_DIDIM, collection="default")
            await client.call(TOOL_SEARCH, {"query": "test", "collection": "override"})
            import json

            payload = json.loads(route.calls[0].request.read())
            assert payload["collection"] == "override"

    async def test_call_http_error_raises(self):
        with respx.mock(base_url=BASE_DIDIM) as mock:
            mock.post("/search").mock(return_value=httpx.Response(500))
            client = DidimRagClient(base_url=BASE_DIDIM)
            with pytest.raises(httpx.HTTPStatusError):
                await client.call(TOOL_SEARCH, {"query": "x"})

    async def test_list_tools_from_service(self):
        tools = [{"name": "search"}, {"name": "embed"}]
        with respx.mock(base_url=BASE_DIDIM) as mock:
            mock.get("/tools").mock(return_value=httpx.Response(200, json=tools))
            client = DidimRagClient(base_url=BASE_DIDIM)
            result = await client.list_tools()
            assert result == tools

    async def test_list_tools_fallback_when_service_unavailable(self):
        with respx.mock(base_url=BASE_DIDIM) as mock:
            mock.get("/tools").mock(return_value=httpx.Response(404))
            client = DidimRagClient(base_url=BASE_DIDIM)
            result = await client.list_tools()
            names = {t["name"] for t in result}
            assert TOOL_SEARCH in names
            assert TOOL_EMBED in names

    async def test_context_manager(self):
        async with DidimRagClient(base_url=BASE_DIDIM) as client:
            assert client is not None


# ---------------------------------------------------------------------------
# T2SqlClient
# ---------------------------------------------------------------------------


class TestT2SqlClient:
    async def test_call_query_posts_to_tool_path(self):
        with respx.mock(base_url=BASE_T2SQL) as mock:
            mock.post("/query").mock(
                return_value=httpx.Response(200, json={"sql": "SELECT 1", "rows": [{"count": 1}]})
            )
            client = T2SqlClient(base_url=BASE_T2SQL)
            result = await client.call(TOOL_QUERY, {"question": "How many users?"})
            assert result["sql"] == "SELECT 1"

    async def test_call_injects_schema_hint(self):
        with respx.mock(base_url=BASE_T2SQL) as mock:
            route = mock.post("/query").mock(return_value=httpx.Response(200, json={}))
            client = T2SqlClient(base_url=BASE_T2SQL, schema_hint="users(id, name)")
            await client.call(TOOL_QUERY, {"question": "List users"})
            import json

            payload = json.loads(route.calls[0].request.read())
            assert payload["schema_hint"] == "users(id, name)"

    async def test_call_no_schema_hint_injection_when_empty(self):
        with respx.mock(base_url=BASE_T2SQL) as mock:
            route = mock.post("/query").mock(return_value=httpx.Response(200, json={}))
            client = T2SqlClient(base_url=BASE_T2SQL, schema_hint="")
            await client.call(TOOL_QUERY, {"question": "test"})
            import json

            payload = json.loads(route.calls[0].request.read())
            assert "schema_hint" not in payload

    async def test_call_http_error_raises(self):
        with respx.mock(base_url=BASE_T2SQL) as mock:
            mock.post("/query").mock(return_value=httpx.Response(502))
            client = T2SqlClient(base_url=BASE_T2SQL)
            with pytest.raises(httpx.HTTPStatusError):
                await client.call(TOOL_QUERY, {"question": "x"})

    async def test_list_tools_from_service(self):
        tools = [{"name": "query"}, {"name": "schema"}]
        with respx.mock(base_url=BASE_T2SQL) as mock:
            mock.get("/tools").mock(return_value=httpx.Response(200, json=tools))
            client = T2SqlClient(base_url=BASE_T2SQL)
            result = await client.list_tools()
            assert result == tools

    async def test_list_tools_fallback_when_service_unavailable(self):
        with respx.mock(base_url=BASE_T2SQL) as mock:
            mock.get("/tools").mock(return_value=httpx.Response(503))
            client = T2SqlClient(base_url=BASE_T2SQL)
            result = await client.list_tools()
            names = {t["name"] for t in result}
            assert TOOL_QUERY in names
            assert TOOL_EXPLAIN in names
            assert TOOL_SCHEMA in names

    async def test_context_manager(self):
        async with T2SqlClient(base_url=BASE_T2SQL) as client:
            assert client is not None
