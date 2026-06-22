from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from runtime_common.thread_history.base import UiMessage

logger = logging.getLogger(__name__)


def _text_from_adk_event(event_data: dict[str, Any]) -> str | None:
    content = event_data.get("content")
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text_val = part.get("text")
            if isinstance(text_val, str) and text_val:
                texts.append(text_val)
    if not texts:
        return None
    return "".join(texts)


def _role_from_adk_event(event_data: dict[str, Any]) -> str | None:
    content = event_data.get("content")
    if isinstance(content, dict):
        role = content.get("role")
        if isinstance(role, str):
            normalized = role.lower()
            if normalized in {"user", "assistant", "model"}:
                return "assistant" if normalized == "model" else normalized
    author = event_data.get("author")
    if isinstance(author, str):
        normalized = author.lower()
        if normalized in {"user", "assistant", "model"}:
            return "assistant" if normalized == "model" else normalized
    return None


class AdkThreadHistoryAdapter:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def load_messages(
        self,
        *,
        provider_session_id: str,
        provider_meta: dict,
    ) -> list[UiMessage]:
        app_name = str(provider_meta.get("app_name") or "agent-base")
        adk_user_id = str(provider_meta.get("adk_user_id") or provider_session_id)
        try:
            result = await self._db.execute(
                text(
                    """
                    SELECT event_data
                    FROM events
                    WHERE app_name = :app_name
                      AND user_id = :user_id
                      AND session_id = :session_id
                    ORDER BY timestamp ASC, id ASC
                    """
                ),
                {
                    "app_name": app_name,
                    "user_id": adk_user_id,
                    "session_id": provider_session_id,
                },
            )
        except Exception as exc:
            logger.warning("adk thread history query failed: %s", exc)
            return []

        messages: list[UiMessage] = []
        for row in result.mappings():
            raw = row.get("event_data")
            if raw is None:
                continue
            if isinstance(raw, str):
                try:
                    event_data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
            elif isinstance(raw, dict):
                event_data = raw
            else:
                continue
            role = _role_from_adk_event(event_data)
            text_content = _text_from_adk_event(event_data)
            if role is None or text_content is None:
                continue
            messages.append(UiMessage(role=role, content=text_content))
        return messages
