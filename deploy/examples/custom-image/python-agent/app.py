"""Custom agent image — raw contract example (Python / FastAPI).

Image contract:
  POST /invoke  — receives AgentInvokeRequest body + x-principal, x-runtime-cfg headers
  GET  /healthz — liveness
  GET  /readyz  — readiness

K8s injects:
  RUNTIME_POOL    = "agent:custom:{slug}"
  DEPLOY_API_URL  = "http://deploy-api.runtime.svc.cluster.local:8080"
  POD_NAME / POD_IP / POD_PORT
"""

from __future__ import annotations

import base64
import json
import os

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

app = FastAPI()

RUNTIME_POOL = os.environ.get("RUNTIME_POOL", "agent:custom:unknown")


class InvokeRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict
    session_id: str | None = None
    stream: bool = False


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ok"}


@app.post("/invoke")
async def invoke(
    request: Request,
    body: InvokeRequest,
    x_principal: str | None = Header(default=None),
    x_runtime_cfg: str | None = Header(default=None),
) -> dict:
    # Decode principal (set by ext-authz)
    principal: dict = {}
    if x_principal:
        try:
            principal = json.loads(base64.b64decode(x_principal))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid x-principal header")

    # Decode merged config (source.config + user.config, set by ext-authz)
    cfg: dict = {}
    if x_runtime_cfg:
        try:
            cfg = json.loads(base64.b64decode(x_runtime_cfg))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid x-runtime-cfg header")

    # ── Your agent logic here ──────────────────────────────────────────────
    result = {
        "output": f"Hello from {RUNTIME_POOL}!",
        "input_received": body.input,
        "principal": principal.get("sub"),
        "cfg_keys": list(cfg.keys()),
    }
    # ──────────────────────────────────────────────────────────────────────

    return {"result": result}
