"""訊息類 WS 處理器：send / read / typing / edit / delete / restore / forward / react。

刻意用 `db_module.SessionLocal()`（而非 get_db 依賴）建立 session，
讓測試能 monkeypatch `app.db.SessionLocal` 換成測試用的 factory。
"""

import uuid
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import delete as sa_delete, select

from app import db as db_module
from app.message_policy import (
    EDIT_WINDOW,
    MAX_ATTACHMENTS,
    MAX_ATTACHMENTS_TOTAL_BYTES,
    RECALL_WINDOW,
    RESTORE_WINDOW,
    is_valid_reaction_emoji,
)
from app.models import Attachment, Message, MessageEdit, Reaction, User
from app.services.conversations import (
    get_attachments_for_message,
    get_conversation_for_member,
    get_member_ids,
    get_other_member_ids,
    mark_read,
    read_count as read_count_fn,
)
from app.services.notifications import create_notification, serialize_notification
from app.services.pins import PIN_LIMIT, can_pin, count_pins
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
    attachment_ids_raw = data.get("attachment_ids") or []
    reply_to_message_id_raw = data.get("reply_to_message_id")

    if not isinstance(attachment_ids_raw, list):
        await websocket.send_json(
            {"type": "error", "reason": "invalid_payload", "temp_id": temp_id}
        )
        return
    if not conv_id_raw or (not content and not attachment_ids_raw):
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

    # 解析 + 去重(保序);超過上限即擋。
    seen: set = set()
    att_ids: list = []
    for raw in attachment_ids_raw:
        try:
            aid = uuid.UUID(str(raw))
        except ValueError:
            await websocket.send_json(
                {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
            )
            return
        if aid not in seen:
            seen.add(aid)
            att_ids.append(aid)
    if len(att_ids) > MAX_ATTACHMENTS:
        await websocket.send_json(
            {"type": "error", "reason": "too_many_attachments", "temp_id": temp_id}
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

        attachments: list[Attachment] = []
        if att_ids:
            rows = (await db.execute(
                select(Attachment).where(Attachment.id.in_(att_ids))
            )).scalars().all()
            by_id = {a.id: a for a in rows}
            # 全部都必須存在、屬本人、且尚未綁定(任一不符即整體拒絕,不部分綁定)。
            for aid in att_ids:
                a = by_id.get(aid)
                if a is None or a.uploader_id != user.id or a.message_id is not None:
                    await websocket.send_json(
                        {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
                    )
                    return
                attachments.append(a)
            if sum(a.size for a in attachments) > MAX_ATTACHMENTS_TOTAL_BYTES:
                await websocket.send_json(
                    {"type": "error", "reason": "attachments_too_large", "temp_id": temp_id}
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
            for i, a in enumerate(attachments):
                a.message_id = message.id
                a.position = i  # 依 attachment_ids 順序設定顯示順序
            # 被回覆 → 通知原訊息 sender（與訊息同一 transaction;自己回自己不建）。
            reply_notif = None
            if reply_msg is not None:
                reply_notif = await create_notification(
                    db, user_id=reply_msg.sender_id, type="reply", actor_id=user.id,
                    conversation_id=conv_id, message_id=reply_msg.id,
                )
            await db.commit()
            await db.refresh(message)
            for a in attachments:
                await db.refresh(a)
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
        if (
            msg is None
            or msg.sender_id != user.id
            or msg.deleted_at is not None
            or msg.recalled_at is not None
        ):
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
        if msg is None or msg.sender_id != user.id or msg.recalled_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        was_pinned = msg.pinned_at is not None
        if msg.deleted_at is None:
            msg.deleted_at = datetime.now(timezone.utc)
            if was_pinned:
                msg.pinned_at = None  # 刪除即自動解釘(釘選列不顯示已刪訊息)
            await db.commit()
            await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
        if was_pinned:
            await _broadcast_unpinned(db, msg.conversation_id, user.id, msg.id)


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


async def handle_recall(websocket, user, data):
    """撤回訊息(不可復原):寄件人本人、2 分內、未刪除/未撤回。
    清空 content、移除附件與表情、自動解釘,廣播 message_updated(recalled=true)。
    """
    mid = parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        # 非本人 / 不存在 / 已刪除 / 已撤回 → forbidden(與 edit/delete 一致不洩漏)。
        if (
            msg is None
            or msg.sender_id != user.id
            or msg.deleted_at is not None
            or msg.recalled_at is not None
        ):
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if datetime.now(timezone.utc) - as_utc(msg.created_at) > RECALL_WINDOW:
            await websocket.send_json({"type": "error", "reason": "recall_window_passed"})
            return
        was_pinned = msg.pinned_at is not None
        msg.recalled_at = datetime.now(timezone.utc)
        msg.content = ""
        msg.pinned_at = None  # 撤回即自動解釘
        await db.execute(sa_delete(Attachment).where(Attachment.message_id == msg.id))
        await db.execute(sa_delete(Reaction).where(Reaction.message_id == msg.id))
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
        if was_pinned:
            await _broadcast_unpinned(db, msg.conversation_id, user.id, msg.id)


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

        # 3. 不能轉發已軟刪 / 已撤回訊息
        if orig.deleted_at is not None or orig.recalled_at is not None:
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

        # 6. 複製原訊息的全部附件（各複製一列，共用 stored_name，不動磁碟檔，保留順序）
        for i, att in enumerate(await get_attachments_for_message(db, orig.id)):
            db.add(Attachment(
                message_id=new_msg.id,
                uploader_id=user.id,
                stored_name=att.stored_name,
                original_name=att.original_name,
                content_type=att.content_type,
                size=att.size,
                is_image=att.is_image,
                position=i,
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


async def _broadcast_pinned(db, conv_id, actor_id, message: Message) -> None:
    payload = await serialize_message(db, message, read_count=await read_count_fn(db, message.id))
    for rid in [actor_id, *await get_other_member_ids(db, conv_id, actor_id)]:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message_pinned", "message": payload})


async def _broadcast_unpinned(db, conv_id, actor_id, message_id) -> None:
    for rid in [actor_id, *await get_other_member_ids(db, conv_id, actor_id)]:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {
                "type": "message_unpinned",
                "conversation_id": str(conv_id),
                "message_id": str(message_id),
            })


async def handle_pin(websocket, user, data):
    """釘選訊息。協定:{type:"pin", message_id}。廣播 message_pinned 給對話所有成員。"""
    mid = parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.deleted_at is not None or msg.recalled_at is not None:
            await websocket.send_json({"type": "error", "reason": "not_found"})
            return
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None:
            await websocket.send_json({"type": "error", "reason": "not_found"})
            return
        if not await can_pin(db, conv, user.id):
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if msg.pinned_at is not None:
            # 冪等:已釘 → 不變,仍廣播當前狀態以同步(前端 addPin 去重)。
            await _broadcast_pinned(db, conv.id, user.id, msg)
            return
        if await count_pins(db, conv.id) >= PIN_LIMIT:
            await websocket.send_json({"type": "error", "reason": "pin_limit"})
            return
        msg.pinned_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(msg)
        await _broadcast_pinned(db, conv.id, user.id, msg)


async def handle_unpin(websocket, user, data):
    """取消釘選。協定:{type:"unpin", message_id}。廣播 message_unpinned。"""
    mid = parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None:
            await websocket.send_json({"type": "error", "reason": "not_found"})
            return
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None:
            await websocket.send_json({"type": "error", "reason": "not_found"})
            return
        if not await can_pin(db, conv, user.id):
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if msg.pinned_at is not None:
            msg.pinned_at = None
            await db.commit()
        # 冪等:未釘也廣播 unpinned 以同步(前端 removePin 對不存在者 no-op)。
        await _broadcast_unpinned(db, conv.id, user.id, msg.id)


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
        if conv is None or msg.deleted_at is not None or msg.recalled_at is not None:
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
