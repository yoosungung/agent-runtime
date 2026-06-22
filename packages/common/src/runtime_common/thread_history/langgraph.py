from __future__ import annotations

import logging
from typing import Any

from runtime_common.thread_history.base import UiMessage

logger = logging.getLogger(__name__)


def _message_content(msg: Any) -> str | None:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        parts.append(text_val)
            if parts:
                return "".join(parts)
        kwargs = msg.get("kwargs")
        if isinstance(kwargs, dict):
            nested = kwargs.get("content")
            if isinstance(nested, str):
                return nested
    content_attr = getattr(msg, "content", None)
    if isinstance(content_attr, str):
        return content_attr
    if isinstance(content_attr, list):
        parts = []
        for block in content_attr:
            text_val = getattr(block, "text", None)
            if isinstance(text_val, str):
                parts.append(text_val)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if parts:
            return "".join(parts)
    return None


def _message_role(msg: Any) -> str | None:
    if isinstance(msg, dict):
        role = msg.get("type") or msg.get("role")
        if isinstance(role, str):
            normalized = role.lower()
            if normalized in {"human", "user"}:
                return "user"
            if normalized in {"ai", "assistant"}:
                return "assistant"
    role_attr = getattr(msg, "type", None) or getattr(msg, "role", None)
    if isinstance(role_attr, str):
        normalized = role_attr.lower()
        if normalized in {"human", "user"}:
            return "user"
        if normalized in {"ai", "assistant"}:
            return "assistant"
    return None


def _extract_messages_from_checkpoint(checkpoint: dict[str, Any]) -> list[Any]:
    channel_values = checkpoint.get("channel_values")
    if isinstance(channel_values, dict) and isinstance(channel_values.get("messages"), list):
        return channel_values["messages"]
    if isinstance(checkpoint.get("messages"), list):
        return checkpoint["messages"]
    return []


class LangGraphThreadHistoryAdapter:
    async def load_messages(
        self,
        *,
        provider_session_id: str,
        provider_meta: dict,
    ) -> list[UiMessage]:
        try:
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

            from runtime_common.providers.pg_infra import get_shared_checkpointer
        except ImportError as exc:
            logger.warning("langgraph checkpointer unavailable: %s", exc)
            return []

        try:
            checkpointer = get_shared_checkpointer()
        except RuntimeError as exc:
            logger.warning("shared checkpointer not initialized: %s", exc)
            return []

        if checkpointer is None:
            logger.warning("shared checkpointer not initialized")
            return []

        config = {"configurable": {"thread_id": provider_session_id}}
        try:
            checkpoint_tuple = await checkpointer.aget_tuple(config)
        except Exception as exc:
            logger.warning("langgraph checkpoint load failed for %s: %s", provider_session_id, exc)
            return []

        if checkpoint_tuple is None:
            return []

        checkpoint = checkpoint_tuple.checkpoint
        serde = JsonPlusSerializer()
        raw_messages = _extract_messages_from_checkpoint(checkpoint)
        messages: list[UiMessage] = []
        for raw in raw_messages:
            try:
                msg = serde.loads_typed(raw) if isinstance(raw, tuple) else raw
            except Exception:
                msg = raw
            role = _message_role(msg)
            content = _message_content(msg)
            if role is None or content is None:
                continue
            messages.append(UiMessage(role=role, content=content))
        return messages
