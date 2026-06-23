# Spec — 訊息回覆 / 轉發（message-reply-forward）

- 日期：2026-06-21
- 狀態：設計定案，待核准
- 分支基底：`feat/group-chat`
- 來源：[訊息動作設計](../message-actions/spec.md) 標為「明確不做」的「對訊息回覆（reply）、轉發」。本功能起依 [CLAUDE.md](../../../../CLAUDE.md) 的 SDD workflow 產出 spec/bdd/plan/tasks/acceptance + Playwright。

## Overview

在現有 1對1 + 群組訊息上新增兩項能力：

- **行內引用回覆**：對某則訊息回覆，新訊息泡泡上方顯示被引用訊息的小預覽（寄件人 + 摘要）。
- **單目標轉發**：把一則訊息轉發到自己參與的另一個對話，產生一則新訊息，標示「轉發自 {原作者}」，並連同附件一起轉。

兩者皆延伸既有訊息模型與 WebSocket 即時流，不引入 thread 巢狀視圖、不做多選轉發、不做訊息搜尋。

## Business Requirements

- 使用者能對任一可見訊息（自己或他人、未刪）回覆，讓對話脈絡清楚。
- 使用者能把一則訊息快速轉發到另一個對話，且收訊者看得出這是轉發、來自誰。
- 回覆與轉發都即時送達對話所有在線成員，與既有訊息行為一致。

### 明確不做

- ❌ thread 巢狀視圖 / thread 未讀計數（只做行內引用）
- ❌ 一次轉發到多個對話（單目標）
- ❌ 轉發到非自己參與的對話、轉發已刪訊息
- ❌ 跨對話回覆（reply 限同一對話內）
- ❌ 編輯回覆關係、移除轉發標記

## Functional Requirements

### 回覆

1. Client 送訊息時可帶 `reply_to_message_id`，指向**同一對話**內一則未硬刪訊息。
2. 後端驗證該訊息存在且屬於同一 `conversation_id`，否則回 `invalid_reply`。
3. 訊息序列化帶 `reply_to` 預覽：`{ id, sender_id, content, deleted, has_attachment }`；被引用訊息已軟刪時 `content=""`、`deleted=true`。
4. 回覆走既有樂觀更新流程（temp_id / ack）；前端送出前用已載入訊息自建預覽樂觀顯示。
5. 泡泡渲染引用塊；引用塊可點，嘗試捲動到原訊息（若已載入於清單）。

### 轉發

1. Client 送 `{type:"forward", message_id, to_conversation_id}`。
2. 後端驗證：發起人是「原訊息所屬對話」成員（看得到才可轉）；且是「目標對話」成員；原訊息未軟刪。任一不符回 `forbidden`。
3. 在目標對話建新 `Message`：`content` 複製原文、`forwarded_from_user_id` = 原訊息 `sender_id`、不繼承 `reply_to`。
4. 原訊息若有附件 → 複製一筆 `Attachment` 列（沿用同 `stored_name`、同 metadata，不重存檔案）綁到新訊息。
5. 訊息序列化帶 `forwarded_from` 預覽：`{ id, display_name }`（原作者，可能非目標對話成員，故由後端附上 display_name）。
6. commit 後以一般 `{type:"message", message}` 廣播給目標對話所有在線成員（含發起人）。轉發非樂觀（無 temp_id）。

## Acceptance Criteria

- 對訊息回覆後，發送者與收訊者的該則泡泡都顯示引用塊（寄件人名 + 摘要）。
- 引用已軟刪訊息時，引用塊顯示「原訊息已刪除」。
- 跨對話的 `reply_to_message_id` 被拒（`invalid_reply`），不建訊息。
- 轉發文字訊息後，目標對話出現新訊息且標「轉發自 {原作者}」。
- 轉發帶圖片/檔案的訊息後，目標對話的新訊息可顯示/下載同一個附件。
- 轉發到非成員對話、轉發看不到的訊息、轉發已刪訊息皆被拒（`forbidden`）。
- 後端 pytest 全綠；前端 chat vitest 全綠、tsc 乾淨；Playwright happy-path E2E 通過。

## Edge Cases

- 引用的原訊息在回覆送出後才被刪 → 引用塊下次序列化顯示「原訊息已刪除」（`reply_to.deleted=true`）。
- 轉發的原訊息有附件但磁碟檔遺失 → 下載端點既有 `404 檔案不存在` 行為照舊（不在本功能範圍處理）。
- 轉發到自己正開著的對話 → 新訊息以一般廣播抵達並顯示（含轉發標記）。
- 回覆自己的訊息 → 允許（無寄件人限制）。
- `reply_to_message_id` 或 `to_conversation_id` 非合法 UUID / 缺欄位 → `invalid_payload`。

## API Contracts

### WebSocket Client → Server

```
{type:"message", conversation_id, content, temp_id, attachment_id?, reply_to_message_id?}
{type:"forward", message_id, to_conversation_id}
```

### WebSocket Server → Client

- 既有 `ack` / `message` 不變，但其 `message` 物件新增 `reply_to` / `forwarded_from` 兩塊。
- 錯誤：`{type:"error", reason:"invalid_reply"|"invalid_payload"|"forbidden", temp_id?}`。

### REST（序列化形狀，無新端點）

`MessageOut` 新增：
```
reply_to:       { id: uuid, sender_id: uuid, content: str, deleted: bool, has_attachment: bool } | null
forwarded_from: { id: uuid, display_name: str } | null
```
`GET /conversations/{id}/messages` 的每則訊息照新形狀回傳。

## Data Model Changes

`messages` 表新增兩個 nullable 欄位（一支 Alembic migration 0008）：

```
reply_to_message_id    Uuid  FK→messages.id  ondelete SET NULL  nullable  indexed
forwarded_from_user_id Uuid  FK→users.id     ondelete SET NULL  nullable
```

附件轉發**不新增 schema**：複製既有 `attachments` 的一列、共用 `stored_name`（磁碟檔不重存）。本專案無附件/檔案刪除，故共用檔案安全。

## State Changes

### 後端

- `Message` model + 2 欄位；`_handle_send` 接受並驗證 `reply_to_message_id`；新增 `_handle_forward`。
- `_serialize_message` 與 `list_messages` 輸出 `reply_to` / `forwarded_from`。

### 前端（chat remote）

- contracts：`ReplyPreview` / `ForwardedFrom` 型別、`Message.reply_to?` / `forwarded_from?`、`message` 帶 `reply_to_message_id?`、新 `forward` client 類型。
- `messageStore.makeOptimistic` 接受可選 `replyTo` 預覽。
- Thread 新增 `replyingTo` 狀態（引用橫幅）；`ChatApp` 新增 `forwardMessage` 與 forward picker 狀態。
- `receiveMessage` / `loadConversations` 既有路徑涵蓋轉發抵達，無需新 WS case。

## UI Behaviour

- 每則未刪泡泡的動作列新增「回覆」「轉發」。
- 點「回覆」→ 輸入框上方出現引用橫幅（寄件人名 + 摘要 + ✕）；送出帶 `reply_to_message_id` 後清除。
- 泡泡頂端：`forwarded_from` → 「↪ 轉發自 {display_name}」；`reply_to` → 可點引用塊（已刪顯示「原訊息已刪除」）。
- 點「轉發」→ `ForwardPicker` modal 列出使用者對話，選一個 → 送出、關閉。

## Non-Functional Requirements

- **效能**：每則 reply 多查一次原訊息、每則 forward 多查一次原作者（N+1），與既有 `_build_conversation_out` 一致，MVP 可接受。
- **安全**：轉發雙重成員驗證（來源可見 + 目標成員）；回覆限同對話；已刪訊息不可轉；附件下載沿用既有對話成員授權。
- **相容**：兩欄位 nullable、舊訊息預設 null，無資料回填需求；序列化新欄位為 optional，前端不破壞既有 fixtures。
