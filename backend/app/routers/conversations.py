"""對話清單、建群與歷史訊息（分頁）。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Contact, Conversation, ConversationMember, Message, User
from app.schemas import AttachmentOut, ConversationOut, GroupCreateRequest, MessageOut, UserOut
from app.services.conversations import (
    create_group_conversation,
    get_attachment_for_message,
    get_conversation_for_member,
    get_member_ids,
    get_reaction_groups,
    read_count,
    unread_count,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _build_conversation_out(
    db: AsyncSession, conv: Conversation, me: User
) -> ConversationOut:
    member_ids = await get_member_ids(db, conv.id)
    members = [await db.get(User, uid) for uid in member_ids]
    other = None
    if conv.type == "direct":
        other = next((u for u in members if u.id != me.id), None)

    last_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last = last_res.scalar_one_or_none()
    last_out = None
    if last is not None:
        last_out = MessageOut(
            id=last.id, conversation_id=last.conversation_id, sender_id=last.sender_id,
            content=last.content, created_at=last.created_at,
            read_count=await read_count(db, last.id),
        )

    return ConversationOut(
        id=conv.id,
        type=conv.type,
        name=conv.name,
        other_user=UserOut.model_validate(other) if other else None,
        members=[UserOut.model_validate(u) for u in members],
        last_message=last_out,
        unread_count=await unread_count(db, conv.id, me.id),
    )


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
    conversations = rows.scalars().all()
    out = [await _build_conversation_out(db, c, current_user) for c in conversations]
    out.sort(
        key=lambda c: c.last_message.created_at if c.last_message else datetime.min,
        reverse=True,
    )
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
    return await _build_conversation_out(db, conv, current_user)


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

    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    out = []
    for m in messages:
        deleted = m.deleted_at is not None
        att = None if deleted else await get_attachment_for_message(db, m.id)
        groups = [] if deleted else await get_reaction_groups(db, m.id)
        out.append(
            MessageOut(
                id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
                content="" if deleted else m.content, created_at=m.created_at,
                read_count=await read_count(db, m.id),
                attachment=AttachmentOut.model_validate(att) if att else None,
                edited_at=m.edited_at,
                deleted=deleted,
                reactions=groups,
            )
        )
    return out
