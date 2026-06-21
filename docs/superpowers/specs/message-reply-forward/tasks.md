# Tasks — 訊息回覆 / 轉發

每個 task：小、可獨立 review、可獨立測。後端測試用 `backend/.venv/Scripts/python.exe -m pytest`；前端在 `frontend/chat/` 跑 `npm run test` / `npm run typecheck`。Commit 標題 `[reply-forward][type][scope] …`，內文結尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

## Global Constraints（每個 task 隱含）

- 回覆限**同一對話**；跨對話 `reply_to_message_id` → WS `error reason:"invalid_reply"`。
- 轉發雙重驗證：發起人須為「原訊息對話」成員**且**「目標對話」成員，原訊息未軟刪；否則 `forbidden`。缺 `message_id`/`to_conversation_id` → `invalid_payload`。
- 序列化新欄位：`reply_to {id, sender_id, content, deleted, has_attachment}|null`（原訊息軟刪→`content=""`、`deleted=true`）；`forwarded_from {id, display_name}|null`。系統訊息一律 null。
- 前端 `Message.reply_to?` / `forwarded_from?` 為 **optional**（沿用 `kind?`/`deleted_at?` 風格，不破壞既有 fixtures）。
- 轉發附件：複製一筆 `Attachment` 列、沿用同 `stored_name`/metadata、`message_id`=新訊息、`uploader_id`=發起人；不重存磁碟檔。

---

## Task 1：資料模型 + migration 0008

**Goal**：`messages` 加 `reply_to_message_id`、`forwarded_from_user_id` 兩欄。

**Files**
- 改 `backend/app/models/message.py`：
  ```python
  reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
      Uuid, ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True)
  forwarded_from_user_id: Mapped[uuid.UUID | None] = mapped_column(
      Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
  ```
- 新增 `backend/alembic/versions/0008_reply_forward.py`（revises 0007）：`op.add_column` ×2 + `op.create_index("ix_messages_reply_to_message_id", "messages", ["reply_to_message_id"])`；downgrade 反向。
- 測試 `backend/tests/test_migration_0008.py`：shell-out `alembic upgrade head`（仿 test_message_edit_model 的 migration smoke）斷言兩欄存在。

**AC**：`Base.metadata.create_all` 下 model 可寫入兩欄；`alembic upgrade head` 在乾淨 SQLite 建出兩欄。covers 無 BDD（基礎）。

---

## Task 2：序列化 helper + `MessageOut` 欄位（WS + REST）

**Goal**：`reply_to` / `forwarded_from` 出現在 WS 與 REST 的訊息輸出。

**Files**
- 改 `backend/app/schemas.py`：
  ```python
  class ReplyPreviewOut(BaseModel):
      id: uuid.UUID; sender_id: uuid.UUID; content: str; deleted: bool; has_attachment: bool
  class ForwardedFromOut(BaseModel):
      id: uuid.UUID; display_name: str
  # MessageOut 加：
  reply_to: ReplyPreviewOut | None = None
  forwarded_from: ForwardedFromOut | None = None
  ```
- 改 `backend/app/services/conversations.py`，新增（async，回 dict 或 None，供 WS dict 與 REST schema 共用）：
  ```python
  async def build_reply_preview(db, message) -> dict | None:
      # message.reply_to_message_id None → None
      # 查原訊息；deleted = orig.deleted_at is not None
      # has_attachment = (未刪 且 存在 Attachment(message_id=orig.id))
      # content = "" if deleted else orig.content
      # 回 {id, sender_id, content, deleted, has_attachment}
  async def build_forwarded_from(db, message) -> dict | None:
      # forwarded_from_user_id None → None；查 User → {id, display_name}
  ```
- 改 `backend/app/ws/router.py` `_serialize_message`：加 `"reply_to": await build_reply_preview(db, msg)`、`"forwarded_from": await build_forwarded_from(db, msg)`。
- 改 `backend/app/routers/conversations.py` `list_messages` 的 `MessageOut`：`reply_to=await build_reply_preview(db, m)`、`forwarded_from=await build_forwarded_from(db, m)`（注意 schema 期望 `ReplyPreviewOut`，可用 `ReplyPreviewOut(**d) if d else None`）。
- 系統訊息 payload（`_system_message_payload`）加 `"reply_to": None, "forwarded_from": None`。
- 測試 `backend/tests/test_reply_forward_serialize.py`：直接建帶 `reply_to_message_id` / `forwarded_from_user_id` 的 Message，呼叫歷史 API 斷言兩塊形狀；引用已刪訊息 → `reply_to.deleted=true`、`content=""`。

**AC**：歷史 API 與 WS 廣播都含正確 `reply_to`/`forwarded_from`。covers RF-09（部分）。

---

## Task 3：回覆送訊（`_handle_send` 擴充）

**Goal**：`message` 送訊可帶 `reply_to_message_id`，驗證同對話後落庫、廣播帶引用。

**Files**
- 改 `backend/app/ws/router.py` `_handle_send`：
  - 讀 `reply_to_message_id`（可選）；若有：解析 UUID（失敗 → `invalid_payload`，帶 temp_id）；查該訊息，驗 `msg.conversation_id == conv_id` 且 `deleted_at is None`，否則 `{type:"error", reason:"invalid_reply", temp_id}`。
  - 建 `Message(... reply_to_message_id=reply_id)`。其餘 ack/廣播不變（payload 已含 reply_to 因 Task 2）。
- 測試 `backend/tests/test_ws_reply.py`（starlette TestClient + session_factory）：
  - 回覆同對話訊息 → ack/廣播 `reply_to` 正確（id、sender_id、content）。
  - 跨對話 reply_to → `invalid_reply`，DB 不新增訊息。
  - 引用已刪訊息（先刪再回覆）→ 仍可回覆，`reply_to.deleted=true`。

**AC**：covers RF-01（後端）、RF-04、RF-09。

---

## Task 4：轉發（`_handle_forward` + 附件複製 + 廣播）

**Goal**：`forward` 在目標對話建新訊息（複製內容/附件、記原作者）並廣播。

**Files**
- 改 `backend/app/ws/router.py`：
  - `_handle_client_message` 加 `elif msg_type == "forward": await _handle_forward(...)`。
  - `_handle_forward(websocket, user, data)`：
    1. 解析 `message_id` / `to_conversation_id`（缺/非法 → `invalid_payload`）。
    2. 查原訊息；`get_conversation_for_member(db, orig.conversation_id, user.id)` None → `forbidden`。
    3. `orig.deleted_at is not None` → `forbidden`。
    4. `get_conversation_for_member(db, to_conv_id, user.id)` None → `forbidden`。
    5. 建 `Message(conversation_id=to_conv_id, sender_id=user.id, content=orig.content, forwarded_from_user_id=orig.sender_id)`；flush 取 id。
    6. 查原訊息附件（`get_attachment_for_message`）；有 → `db.add(Attachment(message_id=new.id, uploader_id=user.id, stored_name=att.stored_name, original_name=..., content_type=..., size=..., is_image=...))`。
    7. commit、refresh；`payload = await _serialize_message(db, new)`；廣播 `{type:"message", message:payload}` 給 `get_member_ids(to_conv_id)` 所有在線者。
- 測試 `backend/tests/test_ws_forward.py`：
  - 轉文字 → 目標對話新訊息、`forwarded_from` 帶原作者、廣播給目標成員。
  - 轉帶附件 → 新增一筆 Attachment（同 stored_name、綁新訊息）。
  - 轉到非成員目標 → `forbidden`；轉看不到的訊息 → `forbidden`；轉已刪訊息 → `forbidden`；缺 `to_conversation_id` → `invalid_payload`。

**AC**：covers RF-02、RF-03、RF-05、RF-06、RF-07、RF-08（皆後端）。

---

## Task 5：前端 contracts + messageStore + ChatApp 送訊接線

**Goal**：型別、樂觀回覆預覽、送訊與轉發的 WS 呼叫。

**Files**
- 改 `frontend/contracts/index.ts`：`ReplyPreview`、`ForwardedFrom`、`Message.reply_to?`/`forwarded_from?`（optional）、`message` 變體加 `reply_to_message_id?: string`、新 `{ type:'forward'; message_id; to_conversation_id }`。
- 改 `frontend/chat/src/messageStore.ts`：`makeOptimistic(..., replyTo: ReplyPreview | null = null)` → 設 `reply_to: replyTo, forwarded_from: null`。
- 改 `frontend/chat/src/ChatApp.tsx`：
  - `sendMessage(content, attachmentId?, replyToMessageId?, replyPreview?)`：樂觀訊息帶 `replyPreview`；WS `message` 帶 `reply_to_message_id`。
  - `forwardMessage(messageId, toConversationId)`：`socket.send({type:'forward', message_id, to_conversation_id})`。
- 測試：`frontend/chat/src/messageStore.test.ts` 補樂觀 reply 預覽；`api`/store 既有測試保持綠。

**AC**：typecheck 乾淨、vitest 綠。covers RF-01（前端資料）。

---

## Task 6：Thread 回覆 UI（引用塊 + 引用橫幅 + 回覆鈕）

**Goal**：泡泡渲染引用塊、composer 引用橫幅、回覆動作。

**Files**
- 改 `frontend/chat/src/components/Thread.tsx`：
  - `replyingTo: ChatMessage | null` 狀態；點泡泡「回覆」設定它。
  - composer 上方引用橫幅（寄件人名 + 摘要 + ✕ 取消）；`submit` 帶 `replyingTo` 的 id + 預覽，送出後清空。
  - 泡泡頂端渲染 `message.reply_to`：寄件人名（用 `memberNames[reply_to.sender_id]`）+ 摘要；`reply_to.deleted` → 「原訊息已刪除」；可點，捲動到 `reply_to.id`（若該 id 在 `messages` 中，用既有 ref/`scrollIntoView`，否則無動作）。
  - 動作列（未刪泡泡）加「回覆」鈕；新 props `onReply`（或內部狀態 + `onSendReply`）。對齊既有 props 傳遞風格。
- 測試 `frontend/chat/src/components/Thread.test.tsx` 補：渲染 `reply_to` 引用塊（含已刪佔位）、點「回覆」出現引用橫幅、送出帶 id。

**AC**：vitest 綠、typecheck 乾淨。covers RF-01、RF-09（前端渲染）。

---

## Task 7：轉發 UI（ForwardPicker + 轉發鈕 + 轉發標記）

**Goal**：轉發選對話 + 泡泡轉發標記。

**Files**
- 新增 `frontend/chat/src/components/ForwardPicker.tsx`：props `{ conversations, onPick(convId), onClose }`；列出對話（沿用 Sidebar 的標題邏輯：群組用 name、direct 用對方名），點一個呼叫 `onPick`。
- 改 `frontend/chat/src/components/Thread.tsx`：泡泡動作列加「轉發」鈕 → 呼叫 `onForward(message)`（提到 ChatApp 開 picker）。泡泡頂端渲染 `message.forwarded_from` →「↪ 轉發自 {display_name}」。
- 改 `frontend/chat/src/ChatApp.tsx`：`forwarding: string | null` 狀態；「轉發」鈕開 `ForwardPicker`（傳 conversations）；選定 → `forwardMessage(id, convId)` + 關閉。
- 測試 `frontend/chat/src/components/ForwardPicker.test.tsx`（列對話、選一個呼叫 onPick）；`Thread.test.tsx` 補「轉發自 X」渲染與「轉發」鈕呼叫。

**AC**：vitest 綠、typecheck 乾淨。covers RF-02、RF-03（前端渲染/觸發）。

---

## Task 8：Playwright harness + E2E

**Goal**：首次導入 Playwright；happy-path UI E2E + 伺服器端場景 spec，BDD→Playwright 可追溯。

**Files**
- 新增 `e2e/`：`package.json`(`@playwright/test`)、`playwright.config.ts`、`global-setup`（啟動 backend uvicorn(乾淨 SQLite) + auth/chat build&preview + shell dev，或以 webServer 設定逐一拉起；可重用 CLAUDE.md 的啟動指令）。
- 新增 specs：
  - `e2e/reply.spec.ts`：兩個 context(Alice/Bob)→ Bob 送訊、Alice 回覆 → 雙方看到引用塊（RF-01）。
  - `e2e/forward.spec.ts`：Alice 轉發到 Alice↔Carol → 目標出現「轉發自 Bob」（RF-02）；帶附件版本（RF-03）。
  - `e2e/reply-forward-api.spec.ts`：用 Playwright 的 request/WebSocket 直接驅動，覆蓋 RF-04/05/06/07/08（invalid_reply、invalid_payload、forbidden×3），維持每個 BDD 場景至少一個 Playwright 測試。
- 更新 [acceptance.md](acceptance.md) 的勾選；更新 `progress.md`。

**AC**：`e2e` 至少 happy-path（RF-01/02）通過；環境無法啟動時明確 skip 並回報，不誆稱通過。每個 BDD 場景 (RF-01..09) 對應到至少一個自動化測試（Playwright 或 pytest），traceability 記於 acceptance.md。

---

## BDD → Test 追溯總表

| BDD | 主要覆蓋 |
|---|---|
| RF-01 回覆引用塊 | Task 3(pytest) + Task 6(vitest) + Task 8(`reply.spec`) |
| RF-02 轉發標來源 | Task 4(pytest) + Task 7(vitest) + Task 8(`forward.spec`) |
| RF-03 轉發帶附件 | Task 4(pytest) + Task 8(`forward.spec`) |
| RF-04 跨對話回覆拒 | Task 3(pytest) + Task 8(`api.spec`) |
| RF-05 缺欄位轉發拒 | Task 4(pytest) + Task 8(`api.spec`) |
| RF-06 轉非成員拒 | Task 4(pytest) + Task 8(`api.spec`) |
| RF-07 轉看不到的訊息拒 | Task 4(pytest) + Task 8(`api.spec`) |
| RF-08 轉已刪訊息拒 | Task 4(pytest) + Task 8(`api.spec`) |
| RF-09 引用已刪佔位 | Task 2/3(pytest) + Task 6(vitest) |
