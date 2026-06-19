"""WebSocket 連線管理：記錄誰在線、把訊息推給特定使用者。

以單一程序的記憶體儲存連線；多 worker / 水平擴充時需改用 Redis pub/sub 之類的共享層。
"""

import uuid
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """維護 user_id → 一組 WebSocket（同一使用者可能多分頁/裝置）。"""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)

    def disconnect(self, user_id: uuid.UUID, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id)
        if not conns:
            return
        conns.discard(websocket)
        if not conns:
            self._connections.pop(user_id, None)

    def is_online(self, user_id: uuid.UUID) -> bool:
        return bool(self._connections.get(user_id))

    async def send_to_user(self, user_id: uuid.UUID, payload: dict) -> None:
        # 推給該使用者的所有連線；用 list() 複製避免送訊息途中改動集合。
        for ws in list(self._connections.get(user_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:
                # 連線可能已壞；移除之，避免之後重複嘗試。
                self.disconnect(user_id, ws)


manager = ConnectionManager()
