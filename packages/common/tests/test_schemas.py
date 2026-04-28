"""Unit tests for runtime_common.schemas."""

import json

import pytest

from runtime_common.schemas import (
    AgentInvokeRequest,
    AgentRuntimeKind,
    McpInvokeRequest,
    McpRuntimeKind,
    Principal,
    ResolveResponse,
    ResourceRef,
    SourceMeta,
    UserMeta,
    image_mode_service_name,
    parse_runtime_pool,
)


# ---------------------------------------------------------------------------
# parse_runtime_pool
# ---------------------------------------------------------------------------


def test_parse_bundle_mode_agent():
    pid = parse_runtime_pool("agent:compiled_graph")
    assert pid.kind == "agent"
    assert pid.runtime_kind == "compiled_graph"
    assert pid.slug is None
    assert not pid.is_image_mode
    assert str(pid) == "agent:compiled_graph"


def test_parse_bundle_mode_mcp():
    pid = parse_runtime_pool("mcp:fastmcp")
    assert pid.kind == "mcp"
    assert pid.runtime_kind == "fastmcp"
    assert pid.slug is None


def test_parse_image_mode():
    pid = parse_runtime_pool("agent:custom:summarizer-v1")
    assert pid.kind == "agent"
    assert pid.runtime_kind == "custom"
    assert pid.slug == "summarizer-v1"
    assert pid.is_image_mode
    assert str(pid) == "agent:custom:summarizer-v1"


def test_parse_image_mode_mcp():
    pid = parse_runtime_pool("mcp:custom:my-mcp-v2-0")
    assert pid.slug == "my-mcp-v2-0"
    assert pid.is_image_mode


def test_parse_invalid_format():
    with pytest.raises(ValueError, match="invalid runtime_pool"):
        parse_runtime_pool("agent")


def test_parse_three_parts_non_custom():
    with pytest.raises(ValueError, match="custom"):
        parse_runtime_pool("agent:compiled_graph:something")


def test_parse_slug_too_long():
    slug = "a" * 46
    with pytest.raises(ValueError, match="slug"):
        parse_runtime_pool(f"agent:custom:{slug}")


def test_parse_slug_invalid_chars():
    with pytest.raises(ValueError, match="slug"):
        parse_runtime_pool("agent:custom:MY_AGENT")


def test_image_mode_service_name():
    pid = parse_runtime_pool("agent:custom:summarizer-v1")
    assert image_mode_service_name(pid) == "agent-pool-custom-summarizer-v1"


def test_image_mode_service_name_requires_slug():
    pid = parse_runtime_pool("agent:compiled_graph")
    with pytest.raises(ValueError):
        image_mode_service_name(pid)


def test_source_meta_roundtrip():
    sm = SourceMeta(
        kind="agent",
        name="chat-bot",
        version="v1",
        runtime_pool="agent:compiled_graph",
        entrypoint="app:build_graph",
        bundle_uri="s3://bucket/chat-bot-v1.zip",
        checksum="sha256:abc123",
    )
    data = json.loads(sm.model_dump_json())
    sm2 = SourceMeta.model_validate(data)
    assert sm2.name == "chat-bot"
    assert sm2.checksum == "sha256:abc123"


def test_user_meta_roundtrip():
    um = UserMeta(
        principal_id="u_42",
        config={"max_tools": 5},
        secrets_ref="vault://agents/u42",
    )
    data = json.loads(um.model_dump_json())
    um2 = UserMeta.model_validate(data)
    assert um2.principal_id == "u_42"
    assert um2.config["max_tools"] == 5


def test_resolve_response_roundtrip():
    sm = SourceMeta(
        kind="mcp",
        name="rag",
        version="v2",
        runtime_pool="mcp:fastmcp",
        entrypoint="server:make",
        bundle_uri="file:///bundles/rag.zip",
    )
    rr = ResolveResponse(source=sm)
    data = json.loads(rr.model_dump_json())
    rr2 = ResolveResponse.model_validate(data)
    assert rr2.user is None
    assert rr2.source.name == "rag"


def test_resolve_response_with_user():
    sm = SourceMeta(
        kind="agent",
        name="x",
        version="v1",
        runtime_pool="agent:custom",
        entrypoint="m:f",
        bundle_uri="file:///x.zip",
    )
    um = UserMeta(principal_id="p1", config={})
    rr = ResolveResponse(source=sm, user=um)
    assert rr.user is not None
    assert rr.user.principal_id == "p1"


def test_principal_can_access():
    p = Principal(
        sub="alice",
        user_id=1,
        access=[
            ResourceRef(kind="agent", name="chat-bot"),
            ResourceRef(kind="mcp", name="rag"),
        ],
    )
    assert p.can_access("agent", "chat-bot")
    assert p.can_access("mcp", "rag")
    assert not p.can_access("agent", "other")
    assert not p.can_access("mcp", "chat-bot")


def test_principal_empty_access():
    p = Principal(sub="bob", user_id=2)
    assert p.access == []
    assert not p.can_access("agent", "anything")


def test_principal_grace_applied_default():
    p = Principal(sub="c", user_id=3)
    assert p.grace_applied is False


def test_agent_invoke_request_roundtrip():
    req = AgentInvokeRequest(
        agent="chat-bot",
        version="v1",
        input={"message": "hello"},
        session_id="sess-1",
    )
    data = json.loads(req.model_dump_json())
    req2 = AgentInvokeRequest.model_validate(data)
    assert req2.agent == "chat-bot"
    assert req2.session_id == "sess-1"


def test_mcp_invoke_request_roundtrip():
    req = McpInvokeRequest(
        server="rag",
        tool="search",
        arguments={"query": "hello"},
    )
    data = json.loads(req.model_dump_json())
    req2 = McpInvokeRequest.model_validate(data)
    assert req2.tool == "search"
    assert req2.arguments["query"] == "hello"


def test_agent_runtime_kind_values():
    assert AgentRuntimeKind.COMPILED_GRAPH == "compiled_graph"
    assert AgentRuntimeKind.ADK == "adk"
    assert AgentRuntimeKind.CUSTOM == "custom"


def test_mcp_runtime_kind_values():
    assert McpRuntimeKind.FASTMCP == "fastmcp"
    assert McpRuntimeKind.MCP_SDK == "mcp_sdk"
    assert McpRuntimeKind.CUSTOM == "custom"
