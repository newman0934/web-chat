"""1對1 通話訊號中繼（WebRTC signaling）。只在好友之間轉送 SDP / ICE，不落庫。"""

from fastapi import WebSocket

from app import db as db_module
from app.models import User
from app.services.conversations import are_friends
from app.ws.manager import manager
from app.ws.wsutils import parse_uuid

CALL_TYPES = {"call_offer", "call_answer", "call_ice", "call_reject", "call_hangup"}


async def handle_call_signal(websocket: WebSocket, user: User, data: dict) -> None:
    """1對1 通話訊號轉送：只在好友之間轉送 SDP / ICE，不解讀內容、不落庫。"""
    msg_type = data["type"]
    to_id = parse_uuid(data.get("to_user_id"))
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
