from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from runtime_common.chat_threads import ChatThreadType
from runtime_common.thread_history.adk import AdkThreadHistoryAdapter
from runtime_common.thread_history.base import UiMessage
from runtime_common.thread_history.custom import CustomThreadHistoryAdapter
from runtime_common.thread_history.hermes import HermesThreadHistoryAdapter
from runtime_common.thread_history.langgraph import LangGraphThreadHistoryAdapter


async def load_thread_messages(
    db: AsyncSession,
    *,
    thread_type: str,
    provider_session_id: str,
    provider_meta: dict,
) -> list[UiMessage]:
    if thread_type == ChatThreadType.LANGGRAPH:
        adapter = LangGraphThreadHistoryAdapter()
    elif thread_type == ChatThreadType.ADK:
        adapter = AdkThreadHistoryAdapter(db)
    elif thread_type == ChatThreadType.HERMES:
        adapter = HermesThreadHistoryAdapter()
    else:
        adapter = CustomThreadHistoryAdapter()

    return await adapter.load_messages(
        provider_session_id=provider_session_id,
        provider_meta=provider_meta,
    )
