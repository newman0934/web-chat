"""對話清單與歷史訊息（分頁）。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Conversation, Message, User
from app.schemas import ConversationOut, MessageOut, UserOut
from app.services.conversations import get_conversation_for_user, other_user_id

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 我參與的對話 = 我是 user_a 或 user_b 的所有 Conversation。
    result = await db.execute(
        select(Conversation).where(
            or_(
                Conversation.user_a_id == current_user.id,
                Conversation.user_b_id == current_user.id,
            )
        )
    )
    conversations = result.scalars().all()

    # 逐筆組裝清單項目：對方資訊 + 最後一則訊息 + 未讀數。
    # 註：N+1 查詢，對 MVP 的好友量級可接受；量大時可改為聚合查詢。
    out: list[ConversationOut] = []
    for conv in conversations:
        other_id = other_user_id(conv, current_user.id)
        other = await db.get(User, other_id)

        # 最後一則訊息（時間最新）作為清單預覽。
        last_msg_res = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_res.scalar_one_or_none()

        # 未讀 = 對方送來、且尚未標記 read_at 的訊息數。
        unread_res = await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.sender_id != current_user.id,
                Message.read_at.is_(None),
            )
        )
        unread = unread_res.scalar_one()

        out.append(
            ConversationOut(
                id=conv.id,
                other_user=UserOut.model_validate(other),
                last_message=(
                    MessageOut.model_validate(last_msg) if last_msg else None
                ),
                unread_count=unread,
            )
        )

    # 依最後訊息時間排序（新的在前）；沒訊息的排後面
    out.sort(
        key=lambda c: c.last_message.created_at if c.last_message else datetime.min,
        reverse=True,
    )
    return out


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 確認此對話存在且 current_user 是其中一方，否則 404（不洩漏對話存在與否）。
    conv = await get_conversation_for_user(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此對話或無權限"
        )

    # 游標式分頁：撈 before 之前的最新 limit 筆（往回翻舊訊息）。
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()  # DB 取的是新→舊，回傳前翻成舊→新方便前端直接 append 顯示
    return messages
