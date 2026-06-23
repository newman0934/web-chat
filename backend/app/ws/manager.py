"""WebSocket 連線管理：記錄誰在線、把訊息推給特定使用者。

以單一程序的記憶體儲存連線；多 worker / 水平擴充時需改用 Redis pub/sub 之類的共享層。

線上狀態(presence)刻意全部存記憶體:`is_online` 來自連線集合,`last_seen` 也存在這裡。
不從 WebSocket 生命週期寫 DB —— 因為在 starlette TestClient 的關閉路徑中於 WS 端點
disconnect 內開 DB session 會死結,且連線當下頻繁寫入在整體測試下也會誘發 SQLite 死結。
與本專案 presence 既定的「in-memory、單程序」架構一致;跨重啟/多 worker 的耐久化屬未來工作
(可改 Redis 或回填 User.last_seen_at 欄位,該欄位已保留)。
"""

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import WebSocket


class ConnectionManager:
    """維護 user_id → 一組 WebSocket（同一使用者可能多分頁/裝置）。"""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        # user_id → 最後一次離線時間(in-memory)。在線者不在此(以 is_online 判定)。
        self._last_seen: dict[uuid.UUID, datetime] = {}

    def mark_last_seen(self, user_id: uuid.UUID, dt: datetime) -> None:
        self._last_seen[user_id] = dt

    def get_last_seen(self, user_id: uuid.UUID) -> datetime | None:
        return self._last_seen.get(user_id)

    async def connect(self, user_id: uuid.UUID, websocket: WebSocket) -> bool:
        """接受連線並登記。回傳 is_first:該 user 由 0→1 條(剛上線)。"""
        await websocket.accept()
        is_first = len(self._connections.get(user_id, ())) == 0
        self._connections[user_id].add(websocket)
        return is_first

    def disconnect(self, user_id: uuid.UUID, websocket: WebSocket) -> bool:
        """移除連線。回傳 is_last:該 user 由 1→0 條(剛離線)。"""
        conns = self._connections.get(user_id)
        if not conns or websocket not in conns:
            return False
        conns.discard(websocket)
        if not conns:
            self._connections.pop(user_id, None)
            return True
        return False

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
