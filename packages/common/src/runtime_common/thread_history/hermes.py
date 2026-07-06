from __future__ import annotations

import logging

from runtime_common.thread_history.base import UiMessage

logger = logging.getLogger(__name__)


class HermesThreadHistoryAdapter:
    """Load chat history from Hermes SessionDB (provider_session_id = task_id).

    Session message schema is owned by upstream hermes-agent; until we pin a
    stable read API here, thread reload returns empty and the UI keeps in-flight
    messages from the current browser session.
    """

    async def load_messages(
        self,
        *,
        provider_session_id: str,
        provider_meta: dict,
    ) -> list[UiMessage]:
        logger.debug(
            "hermes thread history not yet wired for session %s (meta=%s)",
            provider_session_id,
            provider_meta,
        )
        return []
