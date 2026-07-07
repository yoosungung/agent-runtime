"""Path-graph hybrid RAG — custom MCP container (image mode).

Image contract: POST /invoke, GET /healthz, GET /readyz
Register: POST /api/admin/custom-images (kind=mcp, runtime_pool=mcp:custom:{slug})

Scoped retrieval args (tenant, project_id, project_slug) arrive in body.arguments
when the general agent invokes via knowledge binding.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

RUNTIME_POOL = os.environ.get("RUNTIME_POOL", "mcp:custom:path-graph-rag")


class InvokeRequest(BaseModel):
    server: str
    version: str | None = None
    tool: str
    arguments: dict[str, Any]


def _decode_cfg(header: str | None) -> dict[str, Any]:
    if not header:
        return {}
    try:
        raw = json.loads(base64.b64decode(header))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid x-runtime-cfg header") from exc
    return raw if isinstance(raw, dict) else {}


def _default_top_k(cfg: dict[str, Any]) -> int:
    rag_cfg = cfg.get("path_graph_rag") or {}
    return int(rag_cfg.get("default_top_k", 10))


async def _run_search(arguments: dict[str, Any], *, default_top_k: int) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"hits": [], "results": []}

    tenant = str(arguments.get("tenant") or "")
    project_id = str(arguments.get("project_id") or "")
    project_slug = str(arguments.get("project_slug") or "")
    if not tenant or not project_id or not project_slug:
        raise HTTPException(
            status_code=400,
            detail="tenant, project_id, and project_slug are required (knowledge binding scope)",
        )

    top_k = int(arguments.get("top_k") or default_top_k)
    mode = str(arguments.get("mode") or "auto")
    include_graph = bool(arguments.get("include_graph", False))
    sub_queries = arguments.get("sub_queries") or []
    if isinstance(sub_queries, str):
        sub_queries = [sub_queries]

    from path_graph.admin.retrieval import api_search_project

    payload = await asyncio.to_thread(
        api_search_project,
        tenant,
        project_id,
        query,
        top_k=top_k,
        mode=mode,
        include_graph=include_graph,
        sub_queries=sub_queries or None,
    )
    return {
        "hits": payload.get("hits") or [],
        "results": payload.get("results") or payload.get("hits") or [],
        "mode_resolved": payload.get("mode_resolved"),
        "graph_context": payload.get("graph_context"),
        "sub_queries": payload.get("sub_queries") or [],
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "pool": RUNTIME_POOL}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke(
    body: InvokeRequest,
    x_runtime_cfg: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = _decode_cfg(x_runtime_cfg)
    if body.tool != "search":
        raise HTTPException(status_code=400, detail=f"unknown tool: {body.tool!r}")

    result = await _run_search(body.arguments, default_top_k=_default_top_k(cfg))
    return {"result": result}
