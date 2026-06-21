# Plan — 訊息回覆 / 轉發

執行細節（逐 task 的 TDD 步驟與 AC）見 [tasks.md](tasks.md)。本檔給架構與變更全貌。

## Architecture

延伸既有「訊息走 WebSocket、ConnectionManager 廣播」的設計：
- **回覆**：既有 `message` 送訊多帶 `reply_to_message_id`，重用樂觀更新（temp_id/ack）與廣播。
- **轉發**：新 WS `forward` 類型，後端於目標對話建新訊息（複製內容 + 複製附件列 + 記原作者）後廣播，非樂觀。
- 序列化集中於 `_serialize_message`（WS）與 `list_messages`（REST），兩處同步加 `reply_to` / `forwarded_from`。

## Backend Changes

- `app/models/message.py`：`reply_to_message_id`、`forwarded_from_user_id` 兩 nullable 欄位。
- `alembic/versions/0008_reply_forward.py`：加兩欄 + `reply_to_message_id` 索引。
- `app/schemas.py`：`ReplyPreviewOut`、`ForwardedFromOut`；`MessageOut` 加 `reply_to` / `forwarded_from`。
- `app/services/conversations.py`：helper `build_reply_preview(db, msg)`（查被引用訊息→預覽 dict）、`build_forwarded_from(db, msg)`（查原作者→{id,display_name}）；供 WS 與 REST 共用。
- `app/ws/router.py`：`_handle_send` 接受並驗證 `reply_to_message_id`（同對話）；新增 `_handle_forward`（雙重成員驗證、複製附件列、廣播）；`_serialize_message` 加兩塊；`_handle_client_message` 分派 `forward`。
- `app/routers/conversations.py`：`list_messages` 的 `MessageOut` 加兩塊。

## Frontend Changes

- `frontend/contracts/index.ts`：`ReplyPreview` / `ForwardedFrom`、`Message.reply_to?`/`forwarded_from?`、`message` 帶 `reply_to_message_id?`、新 `forward` client 類型。
- `chat/src/messageStore.ts`：`makeOptimistic` 接受 `replyTo?: ReplyPreview | null`。
- `chat/src/components/ForwardPicker.tsx`：對話清單 modal。
- `chat/src/components/Thread.tsx`：`replyingTo` 狀態 + 引用橫幅；泡泡渲染 `reply_to` / `forwarded_from`；動作列加「回覆」「轉發」。
- `chat/src/ChatApp.tsx`：`sendMessage` 加 `replyToMessageId`；`forwardMessage`；forward picker 狀態接線。

## Database Changes

`messages` 加 `reply_to_message_id`(FK→messages, SET NULL, indexed)、`forwarded_from_user_id`(FK→users, SET NULL)。皆 nullable、舊資料預設 null、無回填。附件無 schema 變更（複製列共用 `stored_name`）。

## API Changes

- WS Client→Server：`message` 多 `reply_to_message_id?`；新 `forward {message_id, to_conversation_id}`。
- 序列化：`MessageOut.reply_to` / `forwarded_from`（WS `ack`/`message` 與 REST 歷史共用）。
- 無新 REST 端點。

## State Management Changes

- zustand store 無新 action：回覆走既有 `ackMessage`/`receiveMessage`/`updateMessage`；轉發走既有 `receiveMessage` + `loadConversations`。
- Thread 元件本地新增 `replyingTo`；ChatApp 本地新增 `forwarding`（被轉發訊息 id）。

## File Changes

新增：`alembic/versions/0008_reply_forward.py`、`chat/src/components/ForwardPicker.tsx`、各對應 test 檔、`e2e/`（Playwright harness + specs）。
修改：`message.py`、`schemas.py`、`services/conversations.py`、`ws/router.py`、`routers/conversations.py`、`contracts/index.ts`、`messageStore.ts`、`Thread.tsx`、`ChatApp.tsx`。

## Risks

- **附件共用檔案**：兩列指向同一 `stored_name`。本專案無檔案刪除，安全；若未來加附件刪除須改為 refcount 或複製檔。
- **Playwright 首次導入**：需把 MF build+preview 三件套 + backend + 乾淨 DB 拉起來；harness 不穩會拖累 CI。緩解：harness 自成一個 task，先跑通一條最小 smoke 再擴充；E2E 可在無法啟動環境時標記 skip 並回報。
- **N+1 序列化**：reply/forward 預覽各多一次查詢；與既有模式一致，MVP 可接受。
- **跨對話資料外洩**：`reply_to` 限同對話、`forwarded_from` 只回 id+display_name（不含原訊息內容），無洩漏。

## Implementation Order

1. 資料模型 + migration 0008
2. 序列化 helper + `MessageOut` 欄位（WS + REST）
3. 回覆送訊（`_handle_send` 擴充 + 驗證）
4. 轉發（`_handle_forward` + 附件複製 + 廣播）
5. 前端 contracts + messageStore + ChatApp 送訊接線
6. Thread 回覆 UI（引用塊、引用橫幅、回覆鈕）
7. 轉發 UI（ForwardPicker + 轉發鈕 + 轉發標記/引用渲染）
8. Playwright harness + happy-path E2E + 伺服器端場景 spec
