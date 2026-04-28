from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.deps import get_principal, get_settings
from backend.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatInvokeRequest(BaseModel):
    agent: str
    version: str | None = None
    input: dict
    session_id: str | None = None
    stream: bool = True


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _extract_text(event: dict) -> str | None:
    """Pull a user-facing text delta from an agent-base SSE event payload.

    agent-base emits three formats depending on runtime_kind:
      - compiled_graph: LangChain `astream_events` v2 — surface only
        `on_chat_model_stream` token deltas.
      - adk: google.adk Event with `content.parts[].text`.
      - custom: `{chunk: ...}` per chunk, or `{output: ...}` final.
    """
    if event.get("event") == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk")
        if isinstance(chunk, dict):
            content = chunk.get("content")
            if isinstance(content, str):
                return content or None
            if isinstance(content, list):
                parts: list[str] = []
                for p in content:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(p.get("text", ""))
                    elif isinstance(p, str):
                        parts.append(p)
                joined = "".join(parts)
                return joined or None
        return None

    content = event.get("content")
    if isinstance(content, dict):
        parts = content.get("parts") or []
        texts = [p["text"] for p in parts if isinstance(p, dict) and p.get("text")]
        if texts:
            return " ".join(texts)

    if "chunk" in event and "event" not in event:
        c = event["chunk"]
        return c if isinstance(c, str) else json.dumps(c)

    if "output" in event:
        out = event["output"]
        if isinstance(out, dict):
            messages = out.get("messages")
            if isinstance(messages, list) and messages:
                last = messages[-1]
                if isinstance(last, dict):
                    c = last.get("content")
                    if isinstance(c, str):
                        return c
            # Try common state-dict keys before falling back to JSON.
            for key in ("output", "response", "answer", "text", "result"):
                val = out.get(key)
                if isinstance(val, str) and val:
                    return val
        return out if isinstance(out, str) else json.dumps(out)

    return None


@router.post("/invoke")
async def chat_invoke(
    body: ChatInvokeRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    await get_principal(request, settings)

    # Use refreshed token if get_principal rotated it; otherwise the cookie.
    token = (
        getattr(request.state, "new_access_token", None)
        or request.cookies.get(settings.ACCESS_TOKEN_COOKIE)
    )
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    url = settings.ENVOY_URL.rstrip("/") + "/v1/agents/invoke"

    payload: dict = {
        "agent": body.agent,
        "input": body.input,
        "stream": body.stream,
    }
    if body.version is not None:
        payload["version"] = body.version
    if body.session_id is not None:
        payload["session_id"] = body.session_id

    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "x-runtime-name": body.agent,
    }
    if body.version:
        headers["x-runtime-version"] = body.version
    if body.session_id:
        headers["x-runtime-session-id"] = body.session_id

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=5.0)
            ) as client:
                async with client.stream(
                    "POST", url, json=payload, headers=headers
                ) as resp:
                    if resp.status_code >= 400:
                        raw = await resp.aread()
                        try:
                            err = json.loads(raw)
                            detail = err.get("detail") or raw.decode(errors="replace")
                        except Exception:
                            detail = raw.decode(errors="replace")
                        yield _sse({"error": f"HTTP {resp.status_code}: {detail}"})
                        return

                    buf = ""
                    async for raw in resp.aiter_bytes():
                        buf += raw.decode("utf-8", errors="replace")
                        while "\n\n" in buf:
                            block, buf = buf.split("\n\n", 1)
                            for line in block.split("\n"):
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].lstrip()
                                if data == "[DONE]":
                                    yield b"data: [DONE]\n\n"
                                    return
                                try:
                                    event = json.loads(data)
                                except json.JSONDecodeError:
                                    continue
                                if "error" in event:
                                    yield _sse({"error": str(event["error"])})
                                    return
                                text = _extract_text(event)
                                if text:
                                    yield _sse({"text": text})
                    yield b"data: [DONE]\n\n"
        except httpx.RequestError as exc:
            logger.warning("chat_gateway_unreachable", extra={"error": str(exc)})
            yield _sse({"error": f"Failed to reach Envoy: {exc}"})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
