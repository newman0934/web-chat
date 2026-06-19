"""對話相關共用邏輯，REST router 與 WebSocket 端點都依賴這裡。

核心是「兩人 → 唯一一筆對話」：用 order_pair 把兩個 user_id 排序後存，
搭配 DB 的 UNIQUE(user_a_id, user_b_id) 保證不會產生重複對話。
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation


def order_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """規範兩個 user_id 的排序（小的當 user_a），避免重複對話。"""
    return (a, b) if str(a) < str(b) else (b, a)


async def get_or_create_conversation(
    db: AsyncSession, user1: uuid.UUID, user2: uuid.UUID
) -> Conversation:
    a, b = order_pair(user1, user2)
    result = await db.execute(
        select(Conversation).where(
            Conversation.user_a_id == a, Conversation.user_b_id == b
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        conv = Conversation(user_a_id=a, user_b_id=b)
        db.add(conv)
        await db.flush()
    return conv


async def get_conversation_for_user(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    """取得對話，且確認 user_id 是其中一方；否則回 None。"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            or_(
                Conversation.user_a_id == user_id,
                Conversation.user_b_id == user_id,
            ),
        )
    )
    return result.scalar_one_or_none()


def other_user_id(conv: Conversation, user_id: uuid.UUID) -> uuid.UUID:
    return conv.user_b_id if conv.user_a_id == user_id else conv.user_a_id
