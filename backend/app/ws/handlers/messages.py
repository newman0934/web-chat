"""訊息類 WS 處理器：send / read / typing / edit / delete / restore / forward / react。

刻意用 `db_module.SessionLocal()`（而非 get_db 依賴）建立 session，
讓測試能 monkeypatch `app.db.SessionLocal` 換成測試用的 factory。
"""

import uuid
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import delete as sa_delete, select

from app import db as db_module
from app.message_policy import EDIT_WINDOW, RESTORE_WINDOW, is_valid_reaction_emoji
from app.models import Attachment, Message, MessageEdit, Reaction, User
from app.services.conversations import (
    get_attachment_for_message,
    get_conversation_for_member,
    get_member_ids,
    get_other_member_ids,
    mark_read,
    read_count as read_count_fn,
)
from app.services.notifications import create_notification, serialize_notification
from app.ws.manager import manager
from app.ws.serializers import serialize_message
from app.ws.wsutils import as_utc, parse_uuid


async def _push_notification(recipient_id: uuid.UUID, payload: dict) -> None:
    """通知建立後，收件人在線即推 server→client {type:"notification"}。"""
    if manager.is_online(recipient_id):
        await manager.send_to_user(recipient_id, {"type": "notification", "notification": payload})


async def _broadcast_updated(db, conv_id, actor_id, message: Message) -> None:
    payload = await serialize_message(db, message, read_count=await read_count_fn(db, message.id))
    recipients = await get_other_member_ids(db, conv_id, actor_id)
    # 含操作者本人（多裝置同步）
    for rid in [actor_id, *recipients]:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message_updated", "message": payload})


async def handle_send(websocket: WebSocket, user: User, data: dict) -> None:
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

    # 若帶了 reply_to_message_id,先在開 DB session 前驗證。
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

        # 驗證被引用的原訊息存在、屬於此對話、
        # 且尚未被軟刪。
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

        payload = await serialize_message(db, message)
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


async def handle_read(websocket: WebSocket, user: User, data: dict) -> None:
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


async def handle_typing(user: User, data: dict) -> None:
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


async def handle_edit(websocket, user, data):
    mid = parse_uuid(data.get("message_id"))
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
        if now - as_utc(msg.created_at) > EDIT_WINDOW:
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


async def handle_delete(websocket, user, data):
    mid = parse_uuid(data.get("message_id"))
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


async def handle_restore(websocket, user, data):
    mid = parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id or msg.deleted_at is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if datetime.now(timezone.utc) - as_utc(msg.deleted_at) > RESTORE_WINDOW:
            await websocket.send_json({"type": "error", "reason": "restore_window_passed"})
            return
        msg.deleted_at = None
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def handle_forward(websocket: WebSocket, user: User, data: dict) -> None:
    """轉發訊息到目標對話：複製內容/附件、記原作者、廣播給目標成員（含發起人）。

    協定：{type:"forward", message_id, to_conversation_id}
    無 temp_id / ack；廣播以一般 {type:"message", message} 傳達。
    """
    msg_id = parse_uuid(data.get("message_id"))
    to_conv_id = parse_uuid(data.get("to_conversation_id"))
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
        payload = await serialize_message(db, new_msg)
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


async def handle_react(websocket, user, data):
    mid = parse_uuid(data.get("message_id"))
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
