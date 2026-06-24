"""訊息置頂的共用邏輯:權限、計數、清單。

權限:direct 兩位成員皆可;group 僅 admin(沿用 ConversationMember.role)。
上限:每對話最多 PIN_LIMIT 則。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message
from app.services.conversations import get_role_map

PIN_LIMIT = 10


async def can_pin(db: AsyncSession, conv: Conversation, user_id: uuid.UUID) -> bool:
    """是否可釘選/取消(呼叫端須已確認 user 為 conv 成員)。"""
    if conv.type == "direct":
        return True
    roles = await get_role_map(db, conv.id)
    return roles.get(user_id) == "admin"


async def count_pins(db: AsyncSession, conversation_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.pinned_at.is_not(None),
            )
        )
    ).scalar_one()


async def list_pins(db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    """該對話的釘選訊息,pinned_at 由新到舊。"""
    return list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.pinned_at.is_not(None),
                )
                .order_by(Message.pinned_at.desc())
            )
        ).scalars().all()
    )
