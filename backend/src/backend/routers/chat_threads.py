from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import check_csrf, get_db, get_principal
from runtime_common.chat_threads import (
    ChatThreadType,
    build_provider_meta,
    thread_type_from_runtime_pool,
)
from runtime_common.db.models import ChatThreadRow, SourceMetaRow
from runtime_common.schemas import Principal
from runtime_common.thread_history import load_thread_messages

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/me/chat",
    tags=["chat-threads"],
    dependencies=[Depends(get_principal)],
)

MAX_TITLE_LEN = 256


class ChatThreadListItem(BaseModel):
    id: str
    agent_name: str
    agent_version: str
    thread_type: str
    title: str
    last_message_at: datetime
    created_at: datetime


class ChatThreadListResponse(BaseModel):
    items: list[ChatThreadListItem]
    total: int
    limit: int
    offset: int


class ChatThreadCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    agent_name: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatThreadResponse(ChatThreadListItem):
    session_id: str


class ChatThreadTouchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, max_length=MAX_TITLE_LEN)


class ChatMessageItem(BaseModel):
    role: str
    content: str


class ChatThreadMessagesResponse(BaseModel):
    messages: list[ChatMessageItem]


def _assert_agent_access(principal: Principal, agent_name: str) -> None:
    if not principal.can_access("agent", agent_name):
        raise HTTPException(status_code=403, detail="No access to this agent")


async def _resolve_latest_agent_source(
    db: AsyncSession,
    agent_name: str,
) -> SourceMetaRow:
    stmt = (
        select(SourceMetaRow)
        .where(
            SourceMetaRow.kind == "agent",
            SourceMetaRow.name == agent_name,
            SourceMetaRow.retired == False,  # noqa: E712
            SourceMetaRow.status != "pending",
        )
        .order_by(SourceMetaRow.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return row


async def _get_owned_thread(
    db: AsyncSession,
    principal: Principal,
    thread_id: str,
) -> ChatThreadRow:
    stmt = select(ChatThreadRow).where(
        ChatThreadRow.id == thread_id,
        ChatThreadRow.user_id == principal.user_id,
        ChatThreadRow.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return row


def _to_list_item(row: ChatThreadRow) -> ChatThreadListItem:
    return ChatThreadListItem(
        id=row.id,
        agent_name=row.agent_name,
        agent_version=row.agent_version,
        thread_type=row.thread_type,
        title=row.title,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
    )


def _to_response(row: ChatThreadRow) -> ChatThreadResponse:
    return ChatThreadResponse(
        **_to_list_item(row).model_dump(),
        session_id=row.provider_session_id,
    )


def _normalize_title(title: str | None) -> str | None:
    if title is None:
        return None
    trimmed = title.strip()
    if not trimmed:
        return None
    if len(trimmed) > MAX_TITLE_LEN:
        return trimmed[: MAX_TITLE_LEN - 3] + "..."
    return trimmed


@router.get("/threads", response_model=ChatThreadListResponse)
async def list_chat_threads(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ChatThreadListResponse:
    base = select(ChatThreadRow).where(
        ChatThreadRow.user_id == principal.user_id,
        ChatThreadRow.deleted_at.is_(None),
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    q = (
        base.order_by(ChatThreadRow.last_message_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    rows = result.scalars().all()
    return ChatThreadListResponse(
        items=[_to_list_item(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/threads",
    response_model=ChatThreadResponse,
    status_code=201,
    dependencies=[Depends(check_csrf)],
)
async def create_chat_thread(
    body: ChatThreadCreateRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ChatThreadResponse:
    _assert_agent_access(principal, body.agent_name)
    source = await _resolve_latest_agent_source(db, body.agent_name)
    try:
        thread_type = thread_type_from_runtime_pool(source.runtime_pool)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)
    provider_session_id = body.session_id or str(uuid.uuid4())
    row = ChatThreadRow(
        id=str(uuid.uuid4()),
        user_id=principal.user_id,
        agent_name=body.agent_name,
        agent_version=source.version,
        thread_type=thread_type.value,
        provider_session_id=provider_session_id,
        provider_meta=build_provider_meta(
            ChatThreadType(thread_type.value),
            principal_user_id=principal.user_id,
        ),
        title="New Chat",
        last_message_at=now,
        created_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.get("/threads/{thread_id}", response_model=ChatThreadResponse)
async def get_chat_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ChatThreadResponse:
    row = await _get_owned_thread(db, principal, thread_id)
    return _to_response(row)


@router.delete(
    "/threads/{thread_id}",
    status_code=204,
    dependencies=[Depends(check_csrf)],
)
async def delete_chat_thread(
    thread_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> None:
    row = await _get_owned_thread(db, principal, thread_id)
    row.deleted_at = datetime.now(UTC)
    await db.commit()


@router.post(
    "/threads/{thread_id}/touch",
    response_model=ChatThreadListItem,
    dependencies=[Depends(check_csrf)],
)
async def touch_chat_thread(
    thread_id: str,
    body: ChatThreadTouchRequest,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ChatThreadListItem:
    row = await _get_owned_thread(db, principal, thread_id)
    normalized = _normalize_title(body.title)
    if normalized is not None:
        row.title = normalized
    row.last_message_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return _to_list_item(row)


@router.get("/threads/{thread_id}/messages", response_model=ChatThreadMessagesResponse)
async def get_chat_thread_messages(
    thread_id: str,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    principal: Principal = Depends(get_principal),  # noqa: B008
) -> ChatThreadMessagesResponse:
    row = await _get_owned_thread(db, principal, thread_id)
    messages = await load_thread_messages(
        db,
        thread_type=row.thread_type,
        provider_session_id=row.provider_session_id,
        provider_meta=row.provider_meta or {},
    )
    return ChatThreadMessagesResponse(
        messages=[ChatMessageItem(role=m.role, content=m.content) for m in messages]
    )
