from __future__ import annotations

import logging

from runtime_common.thread_history.base import UiMessage

logger = logging.getLogger(__name__)


class CustomThreadHistoryAdapter:
    async def load_messages(
        self,
        *,
        provider_session_id: str,
        provider_meta: dict,
    ) -> list[UiMessage]:
        logger.debug(
            "custom thread history not available for session %s",
            provider_session_id,
        )
        return []
