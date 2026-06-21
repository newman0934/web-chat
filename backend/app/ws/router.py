"""WebSocket 端點 `/ws`：即時收發訊息、已讀回執、輸入中狀態。

協定（與前端 frontend/contracts 對齊）：
  Client→Server: {type:"message"|"read"|"typing"|"edit"|"delete"|"react", ...}
  Server→Client: {type:"ack"|"message"|"message_updated"|"read"|"typing"|"error", ...}

刻意用 `db_module.SessionLocal()`（而非 get_db 依賴）建立 session，
讓測試能 monkeypatch `app.db.SessionLocal` 換成測試用的 factory。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as db_module
from app.auth.security import decode_access_token
from app.message_policy import EDIT_WINDOW, RESTORE_WINDOW, is_valid_reaction_emoji
from app.models import Attachment, Message, MessageEdit, Reaction, User
from app.schemas import AttachmentOut
from app.services.conversations import (
    are_friends,
    build_forwarded_from,
    build_reply_preview,
    get_conversation_for_member,
    get_other_member_ids,
    get_reaction_groups,
    mark_read,
    read_count as read_count_fn,
)
from app.ws.manager import manager

router = APIRouter()


def _stringify_uuid_dict(d: dict | None, uuid_keys: list[str]) -> dict | None:
    """把 dict 中指定的 uuid 欄位轉為 str，回傳新 dict（原 dict 不變）。

    Helper for WS path: helpers return native uuid.UUID; WS needs str for JSON.
    """
    if d is None:
        return None
    result = dict(d)
    for k in uuid_keys:
        if k in result and result[k] is not None:
            result[k] = str(result[k])
    return result


async def _serialize_message(db, msg: Message, read_count: int = 0) -> dict:
    deleted = msg.deleted_at is not None
    attachment = None
    if not deleted:
        att_res = await db.execute(select(Attachment).where(Attachment.message_id == msg.id))
        attachment = att_res.scalar_one_or_none()
    groups = [] if deleted else await get_reaction_groups(db, msg.id)

    # reply_to / forwarded_from: helpers return uuid.UUID; stringify for WS JSON.
    reply_to_raw = await build_reply_preview(db, msg)
    forwarded_from_raw = await build_forwarded_from(db, msg)
    reply_to = _stringify_uuid_dict(reply_to_raw, ["id", "sender_id"])
    forwarded_from = _stringify_uuid_dict(forwarded_from_raw, ["id"])

    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": "" if deleted else msg.content,
        "created_at": msg.created_at.astimezone(timezone.utc).isoformat(),
        "read_count": read_count,
        "attachment": (
            AttachmentOut.model_validate(attachment).model_dump(mode="json")
            if attachment else None
        ),
        "edited_at": msg.edited_at.astimezone(timezone.utc).isoformat() if msg.edited_at else None,
        "deleted": deleted,
        "deleted_at": msg.deleted_at.astimezone(timezone.utc).isoformat() if msg.deleted_at else None,
        "reactions": [g.model_dump(mode="json") for g in groups],
        "kind": msg.kind,
        "reply_to": reply_to,
        "forwarded_from": forwarded_from,
    }


async def _resolve_user(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    sub = decode_access_token(token)
    if sub is None:
        return None
    try:
        uid = uuid.UUID(sub)
    except ValueError:
        return None
    return await db.get(User, uid)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    """連線入口：先用 query 的 JWT 驗證，通過才 accept 並進入收訊息迴圈。"""
    async with db_module.SessionLocal() as db:
        user = await _resolve_user(db, token)
    if user is None:
        # 1008 = policy violation；前端據此判斷 token 失效並導回登入。
        await websocket.close(code=1008)
        return

    await manager.connect(user.id, websocket)
    try:
        # 持續接收 client 訊息直到斷線。
        while True:
            data = await websocket.receive_json()
            await _handle_client_message(websocket, user, data)
    except WebSocketDisconnect:
        pass  # 正常斷線
    finally:
        manager.disconnect(user.id, websocket)  # 不論如何都要登出在線狀態


async def _handle_client_message(websocket: WebSocket, user: User, data: dict) -> None:
    msg_type = data.get("type")
    if msg_type == "message":
        await _handle_send(websocket, user, data)
    elif msg_type == "read":
        await _handle_read(websocket, user, data)
    elif msg_type == "typing":
        await _handle_typing(user, data)
    elif msg_type == "edit":
        await _handle_edit(websocket, user, data)
    elif msg_type == "delete":
        await _handle_delete(websocket, user, data)
    elif msg_type == "restore":
        await _handle_restore(websocket, user, data)
    elif msg_type == "react":
        await _handle_react(websocket, user, data)
    elif msg_type in _CALL_TYPES:
        await _handle_call_signal(websocket, user, data)
    else:
        await websocket.send_json({"type": "error", "reason": "unknown_type"})


async def _handle_send(websocket: WebSocket, user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    temp_id = data.get("temp_id")
    attachment_id_raw = data.get("attachment_id")

    if not conv_id_raw or (not content and not attachment_id_raw):
        await websocket.send_json(
            {"type": "error", "reason": "invalid_payload", "temp_id": temp_id}
        )
        return
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except ValueError:
        await websocket.send_json(
            {"type": "error", "reason": "invalid_conversation", "temp_id": temp_id}
        )
        return

    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json(
                {"type": "error", "reason": "forbidden", "temp_id": temp_id}
            )
            return

        attachment = None
        if attachment_id_raw:
            try:
                att_id = uuid.UUID(str(attachment_id_raw))
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
                )
                return
            attachment = await db.get(Attachment, att_id)
            if (
                attachment is None
                or attachment.uploader_id != user.id
                or attachment.message_id is not None
            ):
                await websocket.send_json(
                    {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
                )
                return

        message = Message(conversation_id=conv_id, sender_id=user.id, content=content)
        db.add(message)
        try:
            await db.flush()  # 取得 message.id，尚未 commit
            if attachment is not None:
                attachment.message_id = message.id
            await db.commit()
            await db.refresh(message)
            if attachment is not None:
                await db.refresh(attachment)
        except Exception:
            await db.rollback()
            await websocket.send_json(
                {"type": "error", "reason": "db_error", "temp_id": temp_id}
            )
            return

        payload = await _serialize_message(db, message)
        recipients = await get_other_member_ids(db, conv_id, user.id)

    await websocket.send_json({"type": "ack", "temp_id": temp_id, "message": payload})
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})


async def _handle_read(websocket: WebSocket, user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except (ValueError, TypeError):
        await websocket.send_json({"type": "error", "reason": "invalid_conversation"})
        return

    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        marked = await mark_read(db, conv_id, user.id)
        await db.commit()
        recipients = await get_other_member_ids(db, conv_id, user.id)

    if not marked:
        return
    message_ids = [str(mid) for mid in marked]
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {
                "type": "read",
                "conversation_id": str(conv_id),
                "reader_id": str(user.id),
                "message_ids": message_ids,
            })


async def _handle_typing(user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except (ValueError, TypeError):
        return
    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            return
        recipients = await get_other_member_ids(db, conv_id, user.id)
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(
                rid,
                {"type": "typing", "conversation_id": str(conv_id), "user_id": str(user.id)},
            )


async def _broadcast_updated(db, conv_id, actor_id, message: Message) -> None:
    payload = await _serialize_message(db, message, read_count=await read_count_fn(db, message.id))
    recipients = await get_other_member_ids(db, conv_id, actor_id)
    # 含操作者本人（多裝置同步）
    for rid in [actor_id, *recipients]:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message_updated", "message": payload})


def _parse_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _as_utc(dt: datetime) -> datetime:
    """把可能為 naive 的 datetime 視為 UTC，供時窗比較。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


_CALL_TYPES = {"call_offer", "call_answer", "call_ice", "call_reject", "call_hangup"}


async def _handle_call_signal(websocket: WebSocket, user: User, data: dict) -> None:
    """1對1 通話訊號轉送：只在好友之間轉送 SDP / ICE，不解讀內容、不落庫。"""
    msg_type = data["type"]
    to_id = _parse_uuid(data.get("to_user_id"))
    if to_id is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        friends = await are_friends(db, user.id, to_id)
    if not friends:
        await websocket.send_json({"type": "error", "reason": "forbidden"})
        return

    payload: dict = {
        "type": msg_type,
        "from": {"id": str(user.id), "display_name": user.display_name},
    }
    if msg_type in ("call_offer", "call_answer"):
        payload["sdp"] = data.get("sdp")
    elif msg_type == "call_ice":
        payload["candidate"] = data.get("candidate")

    if manager.is_online(to_id):
        await manager.send_to_user(to_id, payload)
    elif msg_type == "call_offer":
        # 只有撥號（offer）需要回報對方不在線；其餘類型對端已離開，靜默丟棄。
        await websocket.send_json({"type": "call_unavailable", "to_user_id": str(to_id)})


async def _handle_edit(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    content = (data.get("content") or "").strip()
    if mid is None or not content:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id or msg.deleted_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        now = datetime.now(timezone.utc)
        if now - _as_utc(msg.created_at) > EDIT_WINDOW:
            await websocket.send_json({"type": "error", "reason": "edit_window_passed"})
            return
        # 快照目前版本（content + 它的生效時間）後再覆寫。
        prev_at = msg.edited_at or msg.created_at
        db.add(MessageEdit(message_id=msg.id, content=msg.content, created_at=prev_at))
        msg.content = content
        msg.edited_at = now
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def _handle_delete(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if msg.deleted_at is None:
            msg.deleted_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def _handle_restore(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id or msg.deleted_at is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if datetime.now(timezone.utc) - _as_utc(msg.deleted_at) > RESTORE_WINDOW:
            await websocket.send_json({"type": "error", "reason": "restore_window_passed"})
            return
        msg.deleted_at = None
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def _handle_react(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    emoji = data.get("emoji")
    if mid is None or not is_valid_reaction_emoji(emoji):
        await websocket.send_json({"type": "error", "reason": "invalid_reaction"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None or msg.deleted_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        existing = await db.execute(
            select(Reaction).where(
                Reaction.message_id == mid,
                Reaction.user_id == user.id,
                Reaction.emoji == emoji,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            db.add(Reaction(message_id=mid, user_id=user.id, emoji=emoji))
        else:
            await db.execute(sa_delete(Reaction).where(Reaction.id == row.id))
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
