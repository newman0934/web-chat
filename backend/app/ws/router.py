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
    get_attachment_for_message,
    get_conversation_for_member,
    get_member_ids,
    get_other_member_ids,
    get_reaction_groups,
    mark_read,
    read_count as read_count_fn,
)
from app.services.notifications import create_notification, serialize_notification
from app.services.presence import build_presence_event, get_friend_ids
from app.timeutils import to_utc_iso
from app.ws.manager import manager

router = APIRouter()


async def _push_notification(recipient_id: uuid.UUID, payload: dict) -> None:
    """通知建立後，收件人在線即推 server→client {type:"notification"}。"""
    if manager.is_online(recipient_id):
        await manager.send_to_user(recipient_id, {"type": "notification", "notification": payload})


# presence 好友快取:user_id → 好友 id 集合。於「連線」這個健康路徑(可安全讀 DB)填入,
# 「斷線」時直接取用以廣播。WHY 不在斷線 `finally` 內查 DB:starlette TestClient 的關閉
# (teardown join)路徑中於 WS 端點 disconnect 開 DB session 會死結;連線當下頻繁寫 DB 在
# 整體測試下也會誘發 SQLite 死結。故 presence 全程不從 WS 生命週期寫 DB,last_seen 改記在
# 記憶體的 manager(見 ws/manager.py),與 presence「in-memory、單程序」架構一致。
_presence_cache: dict[uuid.UUID, set[uuid.UUID]] = {}


async def _emit_presence(
    friend_ids: set[uuid.UUID],
    user_id: uuid.UUID,
    online: bool,
    last_seen_at: datetime | None,
) -> None:
    """把上/下線事件推給「在線好友」(不碰 DB;離線好友靠下次 /contacts 快照)。"""
    event = build_presence_event(user_id, online, last_seen_at)
    for fid in friend_ids:
        if manager.is_online(fid):
            await manager.send_to_user(fid, event)


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
        "created_at": to_utc_iso(msg.created_at),
        "read_count": read_count,
        "attachment": (
            AttachmentOut.model_validate(attachment).model_dump(mode="json")
            if attachment else None
        ),
        "edited_at": to_utc_iso(msg.edited_at),
        "deleted": deleted,
        "deleted_at": to_utc_iso(msg.deleted_at),
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

    is_first = await manager.connect(user.id, websocket)
    if is_first:
        # 首條連線 = 剛上線:在「健康路徑」讀好友清單並快取(斷線時不再查 DB),廣播 online。
        async with db_module.SessionLocal() as db:
            friend_ids = await get_friend_ids(db, user.id)
        _presence_cache[user.id] = friend_ids
        await _emit_presence(friend_ids, user.id, True, None)
    try:
        # 持續接收 client 訊息直到斷線。
        while True:
            data = await websocket.receive_json()
            await _handle_client_message(websocket, user, data)
    except WebSocketDisconnect:
        pass  # 正常斷線
    finally:
        is_last = manager.disconnect(user.id, websocket)  # 不論如何都要登出在線狀態
        if is_last:
            # 末條連線斷開 = 剛離線:記下 last_seen(記憶體,不碰 DB)再用快取好友清單廣播 offline。
            now = datetime.now(timezone.utc)
            manager.mark_last_seen(user.id, now)
            friend_ids = _presence_cache.pop(user.id, set())
            await _emit_presence(friend_ids, user.id, False, now)


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
    elif msg_type == "forward":
        await _handle_forward(websocket, user, data)
    elif msg_type in _CALL_TYPES:
        await _handle_call_signal(websocket, user, data)
    else:
        await websocket.send_json({"type": "error", "reason": "unknown_type"})


async def _handle_send(websocket: WebSocket, user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    temp_id = data.get("temp_id")
    attachment_id_raw = data.get("attachment_id")
    reply_to_message_id_raw = data.get("reply_to_message_id")

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

    # Validate reply_to_message_id if provided (before opening the DB session).
    reply_id: uuid.UUID | None = None
    if reply_to_message_id_raw is not None:
        try:
            reply_id = uuid.UUID(str(reply_to_message_id_raw))
        except ValueError:
            await websocket.send_json(
                {"type": "error", "reason": "invalid_payload", "temp_id": temp_id}
            )
            return

    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json(
                {"type": "error", "reason": "forbidden", "temp_id": temp_id}
            )
            return

        # Validate that the quoted message exists, belongs to this conversation,
        # and has not been soft-deleted.
        reply_msg: Message | None = None
        if reply_id is not None:
            reply_msg = await db.get(Message, reply_id)
            if (
                reply_msg is None
                or reply_msg.conversation_id != conv_id
                or reply_msg.deleted_at is not None
            ):
                await websocket.send_json(
                    {"type": "error", "reason": "invalid_reply", "temp_id": temp_id}
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

        message = Message(
            conversation_id=conv_id,
            sender_id=user.id,
            content=content,
            reply_to_message_id=reply_id,
        )
        db.add(message)
        try:
            await db.flush()  # 取得 message.id，尚未 commit
            if attachment is not None:
                attachment.message_id = message.id
            # 被回覆 → 通知原訊息 sender（與訊息同一 transaction;自己回自己不建）。
            reply_notif = None
            if reply_msg is not None:
                reply_notif = await create_notification(
                    db, user_id=reply_msg.sender_id, type="reply", actor_id=user.id,
                    conversation_id=conv_id, message_id=reply_msg.id,
                )
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
        notif_push = None
        if reply_notif is not None:
            await db.refresh(reply_notif)
            notif_push = (reply_msg.sender_id, await serialize_notification(db, reply_notif))

    await websocket.send_json({"type": "ack", "temp_id": temp_id, "message": payload})
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})
    if notif_push is not None:
        await _push_notification(*notif_push)


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


async def _handle_forward(websocket: WebSocket, user: User, data: dict) -> None:
    """轉發訊息到目標對話：複製內容/附件、記原作者、廣播給目標成員（含發起人）。

    協定：{type:"forward", message_id, to_conversation_id}
    無 temp_id / ack；廣播以一般 {type:"message", message} 傳達。
    """
    msg_id = _parse_uuid(data.get("message_id"))
    to_conv_id = _parse_uuid(data.get("to_conversation_id"))
    if msg_id is None or to_conv_id is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return

    async with db_module.SessionLocal() as db:
        # 1. 查原訊息
        orig = await db.get(Message, msg_id)
        if orig is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return

        # 2. 確認發起人是原訊息對話的成員（看得到才可轉）
        src_conv = await get_conversation_for_member(db, orig.conversation_id, user.id)
        if src_conv is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return

        # 3. 不能轉發已軟刪訊息
        if orig.deleted_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return

        # 4. 確認發起人是目標對話的成員
        tgt_conv = await get_conversation_for_member(db, to_conv_id, user.id)
        if tgt_conv is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return

        # 5. 建新訊息（不繼承 reply_to）
        new_msg = Message(
            conversation_id=to_conv_id,
            sender_id=user.id,
            content=orig.content,
            forwarded_from_user_id=orig.sender_id,
        )
        db.add(new_msg)
        await db.flush()  # 取得 new_msg.id

        # 6. 若原訊息有附件，複製一列（共用 stored_name，不動磁碟檔）
        att = await get_attachment_for_message(db, orig.id)
        if att is not None:
            db.add(Attachment(
                message_id=new_msg.id,
                uploader_id=user.id,
                stored_name=att.stored_name,
                original_name=att.original_name,
                content_type=att.content_type,
                size=att.size,
                is_image=att.is_image,
            ))

        # 7. 被轉發 → 通知原訊息 sender（conversation 為原訊息所在對話;自己轉自己不建）。
        fwd_notif = await create_notification(
            db, user_id=orig.sender_id, type="forward", actor_id=user.id,
            conversation_id=orig.conversation_id, message_id=orig.id,
        )

        await db.commit()
        await db.refresh(new_msg)

        # 8. 序列化 & 廣播給目標對話所有在線成員（含發起人）
        payload = await _serialize_message(db, new_msg)
        member_ids = await get_member_ids(db, to_conv_id)
        notif_push = None
        if fwd_notif is not None:
            await db.refresh(fwd_notif)
            notif_push = (orig.sender_id, await serialize_notification(db, fwd_notif))

    for uid in member_ids:
        if manager.is_online(uid):
            await manager.send_to_user(uid, {"type": "message", "message": payload})
    if notif_push is not None:
        await _push_notification(*notif_push)


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
        react_notif = None
        if row is None:
            db.add(Reaction(message_id=mid, user_id=user.id, emoji=emoji))
            # 加表情 → 通知被按訊息的 sender（toggle 移除不通知、不刪既有通知）。
            react_notif = await create_notification(
                db, user_id=msg.sender_id, type="reaction", actor_id=user.id,
                conversation_id=msg.conversation_id, message_id=msg.id, emoji=emoji,
            )
        else:
            await db.execute(sa_delete(Reaction).where(Reaction.id == row.id))
        await db.commit()
        await db.refresh(msg)
        notif_push = None
        if react_notif is not None:
            await db.refresh(react_notif)
            notif_push = (msg.sender_id, await serialize_notification(db, react_notif))
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
    if notif_push is not None:
        await _push_notification(*notif_push)
