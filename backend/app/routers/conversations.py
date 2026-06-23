"""對話清單、建群與歷史訊息（分頁）。群組管理(成員/角色/退出/改名)見 group_management.py。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Contact, Conversation, ConversationMember, Message, User
from app.timeutils import coerce_cursor
from app.schemas import ConversationOut, GroupCreateRequest, MessageOut
from app.services.conversations import create_group_conversation, get_conversation_for_member
from app.services.conversation_serializers import (
    serialize_conversation_out,
    serialize_conversations_out,
    serialize_message_out,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == current_user.id)
    )
    conversations = list(rows.scalars().all())
    out = await serialize_conversations_out(db, conversations, current_user)
    # 排序 key 一律正規化成 tz-aware（UTC）：Postgres 的 TIMESTAMPTZ 回 aware、SQLite 回 naive，
    # 兩者混排會 TypeError（can't compare offset-naive and offset-aware）。無訊息對話墊最小時間。
    def _sort_key(c) -> datetime:
        dt = c.last_message.created_at if c.last_message else datetime.min
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    out.sort(key=_sort_key, reverse=True)
    return out


@router.post("/groups", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member_ids = [uid for uid in dict.fromkeys(payload.member_user_ids) if uid != current_user.id]
    if not member_ids:
        raise HTTPException(status_code=400, detail="群組至少要有一位其他成員")
    # 每位成員都必須是好友
    friend_rows = await db.execute(
        select(Contact.contact_user_id).where(Contact.user_id == current_user.id)
    )
    friend_ids = set(friend_rows.scalars().all())
    if any(uid not in friend_ids for uid in member_ids):
        raise HTTPException(status_code=400, detail="只能把好友加入群組")

    conv = await create_group_conversation(db, current_user.id, payload.name, member_ids)
    await db.commit()
    await db.refresh(conv)
    return await serialize_conversation_out(db, conv, current_user)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_for_member(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")

    before = coerce_cursor(db, before)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    return [await serialize_message_out(db, m) for m in messages]
