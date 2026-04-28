"""Custom MCP server image — raw contract example (Python / FastAPI).

Image contract:
  POST /invoke  — receives McpInvokeRequest body + x-principal, x-runtime-cfg headers
  GET  /healthz — liveness
  GET  /readyz  — readiness
"""

from __future__ import annotations

import base64
import json
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

RUNTIME_POOL = os.environ.get("RUNTIME_POOL", "mcp:custom:unknown")


class InvokeRequest(BaseModel):
    server: str
    version: str | None = None
    tool: str
    arguments: dict


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke(
    body: InvokeRequest,
    x_principal: str | None = Header(default=None),
    x_runtime_cfg: str | None = Header(default=None),
) -> dict:
    principal: dict = {}
    if x_principal:
        try:
            principal = json.loads(base64.b64decode(x_principal))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid x-principal header")

    cfg: dict = {}
    if x_runtime_cfg:
        try:
            cfg = json.loads(base64.b64decode(x_runtime_cfg))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid x-runtime-cfg header")

    # ── Your tool dispatch logic here ─────────────────────────────────────
    if body.tool == "echo":
        result = {"echo": body.arguments}
    else:
        raise HTTPException(status_code=400, detail=f"unknown tool: {body.tool}")
    # ──────────────────────────────────────────────────────────────────────

    return {"result": result, "principal": principal.get("sub")}
