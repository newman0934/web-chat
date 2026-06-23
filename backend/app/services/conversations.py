"""對話相關共用邏輯，REST router 與 WebSocket 端點都依賴這裡。

統一模型：direct（2 成員）與 group（N 成員）共用 Conversation/ConversationMember。
direct 用正規化的 direct_key 保證同兩人唯一。
"""

import uuid

from sqlalchemy import func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, Contact, Conversation, ConversationMember, Message, MessageRead, Reaction, User
from app.schemas import ReactionGroupOut


def direct_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """兩個 user_id 排序後組成穩定字串，作為 direct 對話唯一鍵。"""
    x, y = sorted([str(a), str(b)])
    return f"{x}:{y}"


async def get_member_ids(db: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == conversation_id
        )
    )
    return list(rows.scalars().all())


async def get_other_member_ids(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> list[uuid.UUID]:
    return [uid for uid in await get_member_ids(db, conversation_id) if uid != user_id]


async def get_or_create_direct_conversation(
    db: AsyncSession, u1: uuid.UUID, u2: uuid.UUID
) -> Conversation:
    key = direct_key(u1, u2)
    existing = await db.execute(
        select(Conversation).where(Conversation.direct_key == key)
    )
    conv = existing.scalar_one_or_none()
    if conv is not None:
        return conv
    conv = Conversation(type="direct", direct_key=key)
    db.add(conv)
    await db.flush()
    db.add_all([
        ConversationMember(conversation_id=conv.id, user_id=u1),
        ConversationMember(conversation_id=conv.id, user_id=u2),
    ])
    await db.flush()
    return conv


async def create_group_conversation(
    db: AsyncSession, creator_id: uuid.UUID, name: str, member_ids: list[uuid.UUID]
) -> Conversation:
    conv = Conversation(type="group", name=name, creator_id=creator_id)
    db.add(conv)
    await db.flush()
    # 建立者設為 admin，受邀成員設為 member（去重）
    members: list[ConversationMember] = [
        ConversationMember(conversation_id=conv.id, user_id=creator_id, role="admin")
    ]
    for uid in member_ids:
        if uid != creator_id:
            members.append(ConversationMember(conversation_id=conv.id, user_id=uid, role="member"))
    db.add_all(members)
    await db.flush()
    return conv


async def get_conversation_for_member(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    """取得對話，且確認 user 是成員；否則 None。"""
    result = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(
            Conversation.id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def read_count(db: AsyncSession, message_id: uuid.UUID) -> int:
    """讀過此則的人數（MessageRead 不含寄件人，因 mark_read 只標記非自己訊息）。"""
    result = await db.execute(
        select(func.count()).select_from(MessageRead).where(
            MessageRead.message_id == message_id
        )
    )
    return result.scalar_one()


async def unread_count(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    read_subq = select(MessageRead.message_id).where(MessageRead.user_id == user_id)
    result = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            not_(Message.id.in_(read_subq)),
        )
    )
    return result.scalar_one()


async def mark_read(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> list[uuid.UUID]:
    """把此對話中 user 尚未讀、且非自己送出的訊息標記已讀，回傳新標記的 message_ids。"""
    read_subq = select(MessageRead.message_id).where(MessageRead.user_id == user_id)
    rows = await db.execute(
        select(Message.id).where(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            not_(Message.id.in_(read_subq)),
        )
    )
    ids = list(rows.scalars().all())
    db.add_all([MessageRead(message_id=mid, user_id=user_id) for mid in ids])
    await db.flush()
    return ids


async def get_attachment_for_message(
    db: AsyncSession, message_id: uuid.UUID
) -> Attachment | None:
    result = await db.execute(
        select(Attachment).where(Attachment.message_id == message_id)
    )
    return result.scalar_one_or_none()


async def get_reaction_groups(
    db: AsyncSession, message_id: uuid.UUID
) -> list:
    """依 emoji 聚合該訊息的所有 Reaction，回傳 list[ReactionGroupOut]。"""
    rows = await db.execute(
        select(Reaction.emoji, Reaction.user_id).where(Reaction.message_id == message_id)
    )
    by_emoji: dict[str, list[uuid.UUID]] = {}
    for emoji, uid in rows.all():
        by_emoji.setdefault(emoji, []).append(uid)
    return [
        ReactionGroupOut(emoji=e, count=len(uids), user_ids=uids)
        for e, uids in by_emoji.items()
    ]


async def get_role_map(db: AsyncSession, conversation_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """回傳該對話 user_id → role 對照。"""
    rows = await db.execute(
        select(ConversationMember.user_id, ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id
        )
    )
    return {uid: role for uid, role in rows.all()}


async def are_friends(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """雙方是否為好友。加好友為雙向建立兩筆 Contact，故查單向即足。"""
    result = await db.execute(
        select(Contact.id).where(
            Contact.user_id == a,
            Contact.contact_user_id == b,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_member(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> ConversationMember | None:
    res = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    return res.scalar_one_or_none()


async def is_group_admin(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    m = await get_member(db, conversation_id, user_id)
    return m is not None and m.role == "admin"


async def create_system_message(
    db: AsyncSession, conversation_id: uuid.UUID, sender_id: uuid.UUID, content: str
) -> Message:
    msg = Message(
        conversation_id=conversation_id, sender_id=sender_id, content=content, kind="system"
    )
    db.add(msg)
    await db.flush()
    return msg


async def build_reply_preview(db: AsyncSession, message: Message) -> dict | None:
    """被引用原訊息的精簡預覽 dict，供 WS / REST 兩端共用。

    回傳 dict 的 uuid 欄位保留 uuid.UUID 型別（非 str），
    讓 REST 路徑可直接傳給 Pydantic schema，
    WS 路徑在 _serialize_message 裡統一轉 str。
    """
    if message.reply_to_message_id is None:
        return None
    orig = await db.get(Message, message.reply_to_message_id)
    if orig is None:
        # FK SET NULL 後 id 已被清空，或列已被硬刪（不在正常流程中，但防禦）
        return None
    deleted = orig.deleted_at is not None
    content = "" if deleted else orig.content
    has_attachment = (
        (not deleted)
        and (await get_attachment_for_message(db, orig.id)) is not None
    )
    return {
        "id": orig.id,
        "sender_id": orig.sender_id,
        "content": content,
        "deleted": deleted,
        "has_attachment": has_attachment,
    }


async def build_forwarded_from(db: AsyncSession, message: Message) -> dict | None:
    """轉發訊息的原作者資訊 dict，供 WS / REST 兩端共用。

    回傳 dict 的 id 欄位保留 uuid.UUID 型別（非 str），理由同上。
    """
    if message.forwarded_from_user_id is None:
        return None
    user = await db.get(User, message.forwarded_from_user_id)
    if user is None:
        # 原作者帳號已被刪
        return None
    return {
        "id": user.id,
        "display_name": user.display_name,
    }


async def would_leave_groupless_of_admin(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    removing: bool = False,
    new_role: str | None = None,
) -> bool:
    """模擬把 user_id 移除 / 改成 new_role 後，群組是否仍有成員卻 0 個 admin。"""
    role_map = await get_role_map(db, conversation_id)
    if removing:
        role_map.pop(user_id, None)
    elif new_role is not None:
        role_map[user_id] = new_role
    if not role_map:
        return False  # 群空交由刪群邏輯處理
    return not any(r == "admin" for r in role_map.values())
