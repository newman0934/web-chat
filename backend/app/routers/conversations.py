"""對話清單、建群與歷史訊息（分頁）。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Contact, Conversation, ConversationMember, Message, User
from app.timeutils import coerce_cursor, to_utc_iso
from app.schemas import AddMemberRequest, ConversationOut, GroupCreateRequest, GroupRenameRequest, MessageOut, RoleUpdateRequest
from app.services.conversations import (
    create_group_conversation,
    create_system_message,
    get_conversation_for_member,
    get_member,
    get_member_ids,
    is_group_admin,
    serialize_conversation_out,
    serialize_message_out,
    would_leave_groupless_of_admin,
)
from app.ws.manager import manager

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
    conversations = rows.scalars().all()
    out = [await serialize_conversation_out(db, c, current_user) for c in conversations]
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


def _system_message_payload(msg: Message) -> dict:
    """系統訊息的 WS payload（不觸發 ORM lazy-load，欄位皆已知）。"""
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": msg.content,
        "created_at": to_utc_iso(msg.created_at),
        "read_count": 0,
        "attachment": None,
        "edited_at": None,
        "deleted": False,
        "deleted_at": None,
        "reactions": [],
        "kind": "system",
        "reply_to": None,
        "forwarded_from": None,
    }


async def _push_system_and_updated(member_ids, conversation_id, payload) -> None:
    for rid in member_ids:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})
            await manager.send_to_user(
                rid, {"type": "conversation_updated", "conversation_id": str(conversation_id)}
            )


async def _push_removed(user_ids, conversation_id) -> None:
    for rid in user_ids:
        if manager.is_online(rid):
            await manager.send_to_user(
                rid, {"type": "conversation_removed", "conversation_id": str(conversation_id)}
            )


async def _require_group_admin(db, conversation_id, user) -> Conversation:
    """共用守門：對話存在且呼叫者是成員、是 group、且呼叫者為 admin。"""
    conv = await get_conversation_for_member(db, conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="僅群組可管理成員")
    if not await is_group_admin(db, conversation_id, user.id):
        raise HTTPException(status_code=403, detail="僅管理員可執行此操作")
    return conv


@router.post("/{conversation_id}/members", response_model=ConversationOut)
async def add_member(
    conversation_id: uuid.UUID,
    payload: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    if payload.user_id is not None:
        target = await db.get(User, payload.user_id)
    elif payload.email is not None:
        res = await db.execute(select(User).where(User.email == payload.email))
        target = res.scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="需提供 user_id 或 email")
    if target is None:
        raise HTTPException(status_code=404, detail="查無此使用者")
    if await get_member(db, conversation_id, target.id) is not None:
        raise HTTPException(status_code=400, detail="此人已是群組成員")

    db.add(ConversationMember(conversation_id=conversation_id, user_id=target.id, role="member"))
    sys = await create_system_message(
        db, conversation_id, current_user.id,
        f"{current_user.display_name} 把 {target.display_name} 加入群組",
    )
    await db.commit()
    await db.refresh(sys)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    await db.refresh(conv)
    return await serialize_conversation_out(db, conv, current_user)


@router.delete("/{conversation_id}/members/{user_id}", response_model=ConversationOut)
async def remove_member(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能移除自己，請用退出群組")
    target_member = await get_member(db, conversation_id, user_id)
    if target_member is None:
        raise HTTPException(status_code=404, detail="此人不是群組成員")
    if await would_leave_groupless_of_admin(db, conversation_id, user_id, removing=True):
        raise HTTPException(status_code=400, detail="群組需至少一位管理員")

    target = await db.get(User, user_id)
    member_ids_before = await get_member_ids(db, conversation_id)
    await db.delete(target_member)
    sys = await create_system_message(
        db, conversation_id, current_user.id,
        f"{current_user.display_name} 將 {target.display_name} 移出群組",
    )
    await db.commit()
    await db.refresh(sys)

    remaining = [m for m in member_ids_before if m != user_id]
    await _push_system_and_updated(remaining, conversation_id, _system_message_payload(sys))
    await _push_removed([user_id], conversation_id)
    await db.refresh(conv)
    return await serialize_conversation_out(db, conv, current_user)


@router.post("/{conversation_id}/leave")
async def leave_group(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_for_member(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="僅群組可退出")

    member_ids_before = await get_member_ids(db, conversation_id)
    me_member = await get_member(db, conversation_id, current_user.id)

    if len(member_ids_before) == 1:
        # 最後一人退出 → 刪群（成員/訊息 CASCADE）
        await db.delete(conv)
        await db.commit()
        await _push_removed([current_user.id], conversation_id)
        return {"ok": True}

    if await would_leave_groupless_of_admin(db, conversation_id, current_user.id, removing=True):
        raise HTTPException(status_code=400, detail="請先指派另一位管理員再退出")

    await db.delete(me_member)
    sys = await create_system_message(
        db, conversation_id, current_user.id, f"{current_user.display_name} 退出群組"
    )
    await db.commit()
    await db.refresh(sys)

    remaining = [m for m in member_ids_before if m != current_user.id]
    await _push_system_and_updated(remaining, conversation_id, _system_message_payload(sys))
    await _push_removed([current_user.id], conversation_id)
    return {"ok": True}


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_group(
    conversation_id: uuid.UUID,
    payload: GroupRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    conv.name = payload.name.strip()
    sys = await create_system_message(
        db, conversation_id, current_user.id, f"群組已改名為「{conv.name}」"
    )
    await db.commit()
    await db.refresh(sys)
    await db.refresh(conv)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    return await serialize_conversation_out(db, conv, current_user)


@router.patch("/{conversation_id}/members/{user_id}/role", response_model=ConversationOut)
async def set_member_role(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    target_member = await get_member(db, conversation_id, user_id)
    if target_member is None:
        raise HTTPException(status_code=404, detail="此人不是群組成員")
    if target_member.role == payload.role:
        # no-op：不寫系統訊息，直接回現況
        return await serialize_conversation_out(db, conv, current_user)
    if payload.role == "member" and await would_leave_groupless_of_admin(
        db, conversation_id, user_id, new_role="member"
    ):
        raise HTTPException(status_code=400, detail="群組需至少一位管理員")

    target = await db.get(User, user_id)
    target_member.role = payload.role
    text = (
        f"{current_user.display_name} 將 {target.display_name} 設為管理員"
        if payload.role == "admin"
        else f"{current_user.display_name} 取消 {target.display_name} 的管理員"
    )
    sys = await create_system_message(db, conversation_id, current_user.id, text)
    await db.commit()
    await db.refresh(sys)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    await db.refresh(conv)
    return await serialize_conversation_out(db, conv, current_user)
