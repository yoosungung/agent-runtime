from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UiMessage:
    role: str
    content: str


class ThreadHistoryAdapter(Protocol):
    async def load_messages(
        self,
        *,
        provider_session_id: str,
        provider_meta: dict,
    ) -> list[UiMessage]: ...
