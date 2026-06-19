"""WebSocket 端點 `/ws`：即時收發訊息、已讀回執、輸入中狀態。

協定（與前端 frontend/contracts 對齊）：
  Client→Server: {type:"message"|"read"|"typing", ...}
  Server→Client: {type:"ack"|"message"|"read"|"typing"|"error", ...}

刻意用 `db_module.SessionLocal()`（而非 get_db 依賴）建立 session，
讓測試能 monkeypatch `app.db.SessionLocal` 換成測試用的 factory。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as db_module
from app.auth.security import decode_access_token
from app.models import Message, User
from app.schemas import MessageOut
from app.services.conversations import get_conversation_for_user, other_user_id
from app.ws.manager import manager

router = APIRouter()


def _serialize_message(msg: Message) -> dict:
    return MessageOut.model_validate(msg).model_dump(mode="json")


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
    else:
        await websocket.send_json({"type": "error", "reason": "unknown_type"})


async def _handle_send(websocket: WebSocket, user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    temp_id = data.get("temp_id")

    if not conv_id_raw or not content:
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
        conv = await get_conversation_for_user(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json(
                {"type": "error", "reason": "forbidden", "temp_id": temp_id}
            )
            return

        message = Message(
            conversation_id=conv_id, sender_id=user.id, content=content
        )
        db.add(message)
        try:
            await db.commit()
            await db.refresh(message)
        except Exception:
            await db.rollback()
            await websocket.send_json(
                {"type": "error", "reason": "db_error", "temp_id": temp_id}
            )
            return

        payload = _serialize_message(message)
        recipient_id = other_user_id(conv, user.id)

    # ACK 給寄件人（含 temp_id 供前端對齊樂觀訊息）
    await websocket.send_json({"type": "ack", "temp_id": temp_id, "message": payload})
    # 推給收件人（若在線）
    if manager.is_online(recipient_id):
        await manager.send_to_user(recipient_id, {"type": "message", "message": payload})


async def _handle_read(websocket: WebSocket, user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except (ValueError, TypeError):
        await websocket.send_json({"type": "error", "reason": "invalid_conversation"})
        return

    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_user(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        await db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender_id != user.id,
                Message.read_at.is_(None),
            )
            .values(read_at=datetime.now(timezone.utc))
        )
        await db.commit()
        recipient_id = other_user_id(conv, user.id)

    # 通知對方「你的訊息已被讀」
    if manager.is_online(recipient_id):
        await manager.send_to_user(
            recipient_id,
            {"type": "read", "conversation_id": str(conv_id), "reader_id": str(user.id)},
        )


async def _handle_typing(user: User, data: dict) -> None:
    conv_id_raw = data.get("conversation_id")
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except (ValueError, TypeError):
        return
    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_user(db, conv_id, user.id)
        if conv is None:
            return
        recipient_id = other_user_id(conv, user.id)
    if manager.is_online(recipient_id):
        await manager.send_to_user(
            recipient_id,
            {"type": "typing", "conversation_id": str(conv_id), "user_id": str(user.id)},
        )
