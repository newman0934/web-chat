"""WebSocket 端點 `/ws`：連線生命週期、身份驗證、訊息分派、線上狀態廣播。

協定（與前端 frontend/contracts 對齊）：
  Client→Server: {type:"message"|"read"|"typing"|"edit"|"delete"|"restore"|"react"|"forward"|call_*}
  Server→Client: {type:"ack"|"message"|"message_updated"|"read"|"typing"|"presence"|"notification"|"error"|call_*}

各類訊息的實際處理在 app/ws/handlers/（messages.py、calls.py）；序列化在 serializers.py。
本檔只負責：JWT 驗證 → 連線登記/離線 → presence 廣播 → 把訊息分派給對應 handler。

刻意用 `db_module.SessionLocal()`（而非 get_db 依賴）建立 session，
讓測試能 monkeypatch `app.db.SessionLocal` 換成測試用的 factory。
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import db as db_module
from app.auth.deps import resolve_user_from_token
from app.models import User
from app.services.presence import build_presence_event, get_friend_ids
from app.ws.handlers import calls as call_handlers
from app.ws.handlers import messages as msg_handlers
from app.ws.manager import manager

router = APIRouter()


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


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    """連線入口：先用 query 的 JWT 驗證，通過才 accept 並進入收訊息迴圈。"""
    async with db_module.SessionLocal() as db:
        user = await resolve_user_from_token(db, token)
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
        await msg_handlers.handle_send(websocket, user, data)
    elif msg_type == "read":
        await msg_handlers.handle_read(websocket, user, data)
    elif msg_type == "typing":
        await msg_handlers.handle_typing(user, data)
    elif msg_type == "edit":
        await msg_handlers.handle_edit(websocket, user, data)
    elif msg_type == "delete":
        await msg_handlers.handle_delete(websocket, user, data)
    elif msg_type == "restore":
        await msg_handlers.handle_restore(websocket, user, data)
    elif msg_type == "react":
        await msg_handlers.handle_react(websocket, user, data)
    elif msg_type == "pin":
        await msg_handlers.handle_pin(websocket, user, data)
    elif msg_type == "unpin":
        await msg_handlers.handle_unpin(websocket, user, data)
    elif msg_type == "recall":
        await msg_handlers.handle_recall(websocket, user, data)
    elif msg_type == "forward":
        await msg_handlers.handle_forward(websocket, user, data)
    elif msg_type in call_handlers.CALL_TYPES:
        await call_handlers.handle_call_signal(websocket, user, data)
    else:
        await websocket.send_json({"type": "error", "reason": "unknown_type"})
