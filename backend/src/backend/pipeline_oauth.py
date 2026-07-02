from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.settings import Settings
from backend.pipeline_domain import SourceDriver, refresh_token_env_key

logger = logging.getLogger(__name__)

_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_MS_AUTH = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_MS_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
MS_SCOPES = ["offline_access", "Files.Read.All", "Sites.Read.All"]


def _state_key(settings: Settings) -> bytes:
    raw = settings.PIPELINE_OAUTH_STATE_KEY or settings.POSTGRES_DSN or "dev-pipeline-oauth"
    return hashlib.sha256(raw.encode()).digest()


def sign_oauth_state(payload: dict[str, Any], settings: Settings) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_state_key(settings), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_oauth_state(state: str, settings: Settings, *, max_age_sec: int = 600) -> dict[str, Any]:
    if "." not in state:
        raise ValueError("invalid oauth state")
    body, sig = state.rsplit(".", 1)
    expected = hmac.new(_state_key(settings), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("oauth state signature mismatch")
    payload = json.loads(base64.urlsafe_b64decode(body.encode()))
    issued = int(payload.get("ts", 0))
    if time.time() - issued > max_age_sec:
        raise ValueError("oauth state expired")
    return payload


def gdrive_authorize_url(settings: Settings, *, tenant: str, credential_id: str) -> str:
    if not settings.PIPELINE_GDRIVE_CLIENT_ID:
        raise ValueError("PIPELINE_GDRIVE_CLIENT_ID is not configured")
    state = sign_oauth_state(
        {"tenant": tenant, "credential_id": credential_id, "driver": "gdrive", "ts": int(time.time())},
        settings,
    )
    params = {
        "client_id": settings.PIPELINE_GDRIVE_CLIENT_ID,
        "redirect_uri": settings.PIPELINE_GDRIVE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GDRIVE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_GOOGLE_AUTH}?{urlencode(params)}"


async def exchange_gdrive_code(settings: Settings, code: str) -> dict[str, str]:
    if not settings.PIPELINE_GDRIVE_CLIENT_ID or not settings.PIPELINE_GDRIVE_CLIENT_SECRET:
        raise ValueError("Google OAuth app credentials are not configured")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.PIPELINE_GDRIVE_CLIENT_ID,
                "client_secret": settings.PIPELINE_GDRIVE_CLIENT_SECRET,
                "redirect_uri": settings.PIPELINE_GDRIVE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        detail = resp.json().get("error_description", resp.text)
        raise ValueError(f"Google token exchange failed: {detail}")
    data = resp.json()
    refresh = data.get("refresh_token", "").strip()
    if not refresh:
        raise ValueError("Google did not return a refresh_token — revoke app access and retry")
    return {"GDRIVE_REFRESH_TOKEN": refresh}


def ms_authorize_url(settings: Settings, *, tenant: str, credential_id: str) -> str:
    if not settings.PIPELINE_MS_CLIENT_ID:
        raise ValueError("PIPELINE_MS_CLIENT_ID is not configured")
    ms_tenant = settings.PIPELINE_MS_TENANT_ID or "common"
    state = sign_oauth_state(
        {
            "tenant": tenant,
            "credential_id": credential_id,
            "driver": "sharepoint",
            "ts": int(time.time()),
        },
        settings,
    )
    params = {
        "client_id": settings.PIPELINE_MS_CLIENT_ID,
        "redirect_uri": settings.PIPELINE_MS_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(MS_SCOPES),
        "state": state,
    }
    return _MS_AUTH.format(tenant=ms_tenant) + "?" + urlencode(params)


async def exchange_ms_code(settings: Settings, code: str) -> dict[str, str]:
    if not settings.PIPELINE_MS_CLIENT_ID or not settings.PIPELINE_MS_CLIENT_SECRET:
        raise ValueError("Microsoft OAuth app credentials are not configured")
    ms_tenant = settings.PIPELINE_MS_TENANT_ID or "common"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            _MS_TOKEN.format(tenant=ms_tenant),
            data={
                "code": code,
                "client_id": settings.PIPELINE_MS_CLIENT_ID,
                "client_secret": settings.PIPELINE_MS_CLIENT_SECRET,
                "redirect_uri": settings.PIPELINE_MS_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        detail = resp.json().get("error_description", resp.text)
        raise ValueError(f"Microsoft token exchange failed: {detail}")
    data = resp.json()
    refresh = data.get("refresh_token", "").strip()
    if not refresh:
        raise ValueError("Microsoft did not return a refresh_token")
    return {"MS_REFRESH_TOKEN": refresh}


def secrets_for_driver(driver: SourceDriver, token_payload: dict[str, str]) -> dict[str, str]:
    key = refresh_token_env_key(driver)
    if driver == SourceDriver.ONEDRIVE:
        return {
            key: token_payload.get("MS_REFRESH_TOKEN", ""),
            "ONEDRIVE_REFRESH_TOKEN": token_payload.get("MS_REFRESH_TOKEN", ""),
        }
    return {key: token_payload.get(key, "")}
