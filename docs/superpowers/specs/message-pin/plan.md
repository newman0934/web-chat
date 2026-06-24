# 訊息置頂（message-pin）Plan

## 架構決策

- 釘選狀態存 `messages.pinned_at`（nullable timestamp）；`pinned = pinned_at IS NOT NULL`。
- 釘選/取消走 **WebSocket**（與 edit/delete/react 同套路，即時廣播）；釘選清單載入走 **REST**。
- 權限：direct 兩位成員皆可；group 僅 admin（沿用既有角色判斷）。
- 上限 10：釘選前以 `COUNT(pinned_at IS NOT NULL)` 檢查。
- 刪除已釘訊息 → 在既有刪除流程順手清 `pinned_at` 並廣播 `message_unpinned`。
- 釘選列點擊跳轉沿用 message-search 的 `around` 視窗載入 + 高亮（不重造）。

## 後端檔案

- `alembic/versions/0012_message_pinned_at.py`（新）：
  `op.add_column("messages", pinned_at timestamptz null)` +
  `op.create_index("ix_messages_conversation_pinned", "messages", ["conversation_id", "pinned_at"])`；
  downgrade 反向。
- `app/models/message.py`：加 `pinned_at: Mapped[datetime | None]`。
- `app/schemas.py`：`MessageOut` 加 `pinned: bool`。
- `app/services/conversation_serializers.py`：`serialize_message_out` / `serialize_messages_out`
  填 `pinned = m.pinned_at is not None`。
- `app/services/pins.py`（新）：
  - `PIN_LIMIT = 10`。
  - `async def can_pin(db, conversation_id, user_id) -> bool`（direct→成員即可；group→admin）。
  - `async def list_pins(db, conversation_id) -> list[Message]`（pinned_at desc）。
  - `async def count_pins(db, conversation_id) -> int`。
- `app/ws/handlers/messages.py`：加 `handle_pin` / `handle_unpin`：
  - 取訊息、驗成員（非成員/不存在 → error not_found）、驗 `can_pin`（group 非 admin → forbidden）。
  - pin：已釘 → 冪等回（仍廣播或略過）；未釘且 `count_pins >= PIN_LIMIT` → error pin_limit；
    否則 `pinned_at=now()`、commit、廣播 `message_pinned`（serialize_message_out）。
  - unpin：未釘 → 冪等；否則清 `pinned_at`、commit、廣播 `message_unpinned`。
- `app/ws/router.py`：dispatch 加 `pin` / `unpin`。
- `app/ws/handlers/messages.py`（既有 delete）：刪除時若 `pinned_at` 非空 → 一併清空並廣播
  `message_unpinned`。
- `app/routers/conversations.py`：`GET /{conversation_id}/pins` → `list_pins` + `serialize_messages_out`。
- 廣播 helper：沿用既有「推給對話所有成員」的工具（與 message_updated 相同路徑）。

## 前端檔案（frontend/chat）

- `contracts/index.ts`：`Message` 加 `pinned?: boolean`；`ServerWsMessage` 加
  `message_pinned` / `message_unpinned`；`ClientWsMessage` 加 `pin` / `unpin`。
- `src/api.ts`：`listPins(conversationId)`。
- `src/pins.ts`（新，純函式）：
  - `canPin(conversation, userId)`（direct→true；group→roles[userId]==='admin'）。
  - `pinnedBarView(pins)`（最新一則 + 總數；空 → null）。
  - `addPin / removePin`（pins 陣列增減,維持 pinned_at desc、去重）。
- `src/store.ts`：`pins: Record<convId, Message[]>` + actions（setPins / addPin / removePin）。
- `src/wsDispatch.ts`：`message_pinned` → addPin（並更新該訊息 pinned）；
  `message_unpinned` → removePin。
- `src/useMessageActions.ts`：`pinMessage` / `unpinMessage`（wsSend）。
- `src/components/PinnedBar.tsx`（新）：釘選列（最新 + 共 N 則 + 展開清單 + 點擊跳轉/取消）。
- `src/components/MessageBubble.tsx`：動作選單加「釘選/取消釘選」（依 canPin）、已釘顯示 📌。
- `src/components/Thread.tsx`：header 下方掛 `PinnedBar`，點擊轉呼 jumpToMessage（沿用既有）。
- `src/ChatApp.tsx`：開啟對話時 `listPins` → setPins；接 pin/unpin actions 與 PinnedBar 跳轉。

## 測試策略

- **後端 pytest**（`tests/test_pins.py`、`tests/test_migration_0012.py`）：
  pin/unpin 廣播、direct 雙方可、group 僅 admin、非成員/not_found、上限 10、取消後可再釘、
  冪等、刪除自動解釘、GET pins 清單與權限；migration smoke。雙環境關鍵案例。
- **前端 vitest**（`src/pins.test.ts`）：canPin（direct/group admin/非 admin）、pinnedBarView、
  addPin/removePin（排序、去重、上限不在前端強制但顯示正確）。
- **e2e**（`pin-api.spec.ts` WS+REST、`pin-ui.spec.ts` UI）：對應 MP-01..10。

## 風險與緩解

- 釘選列點擊跳轉的時序：沿用 message-search 既驗證的 `around` + 高亮機制。
- 同秒/分頁類問題不涉入（pins 數量 ≤ 10，直接清單）。
- 刪除流程改動：只在既有 delete handler 末尾加「若已釘則解釘並廣播」，不改其他語意。

## 不做（YAGNI）

記錄釘選者、釘選排序自訂、釘選通知、跨對話釘選、釘選歷史。
