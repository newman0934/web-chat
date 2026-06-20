# 訊息編輯 / 刪除 / 表情回應 — 設計文件

- 日期：2026-06-20
- 狀態：設計定案，待 review
- 範圍：在現有聊天（1對1 + 群組 + 附件）上新增訊息編輯、軟刪除、表情回應
- 前置：原列於 [MVP 設計文件](2026-06-19-chat-web-mvp-design.md) 的「明確不做」，經使用者要求納入。建立在 `feat/group-chat` 分支之上。

## 1. 目標與範圍

讓使用者對既有訊息進行三種動作：編輯、刪除、表情回應。三者共用「對既有訊息的即時變更」模型，皆走 WebSocket 並廣播給對話成員。

### 驗收範圍（最小可用）

- ✅ 編輯訊息（只有寄件人；覆蓋內容、標記「已編輯」）
- ✅ 刪除訊息（軟刪除；顯示「此訊息已刪除」佔位）
- ✅ 表情回應（固定 6 個快速 emoji；任何成員可加/移除；顯示各 emoji 計數）
- ✅ 三種變更皆即時同步給對話所有在線成員

### 明確不做（之後擴充）

- ❌ 編輯歷史 / 版本紀錄、編輯時間限制
- ❌ 自由 emoji 選擇器（只用固定 6 個）
- ❌ 還原已刪除訊息
- ❌ 對訊息回覆（reply / thread）、轉發
- ❌ 表情回應的通知

## 2. 核心決策

採**方案 A：沿用 WebSocket 協定**。新增 client→server 類型 `edit` / `delete` / `react`，server→client 用單一 `message_updated` 事件廣播「更新後的完整訊息」給對話所有在線成員（含操作者本人，利於多裝置同步）。完全重用既有 WS 連線、`get_conversation_for_member` 權限、群組廣播與 `ConnectionManager`；前端依 `message.id` upsert。

替代方案 B（REST `PATCH/DELETE /messages/{id}` + 反應端點，再 WS 通知）已否決：把改訊息拆成「REST 改 + WS 通知」兩步，與既有「送訊息走 WS」不一致，廣播邏輯仍須重寫。

## 3. 資料模型（SQLAlchemy）

```
Message（新增兩欄位）
  edited_at   DateTime(tz) NULL    # 編輯後填入；非空 → 顯示「已編輯」
  deleted_at  DateTime(tz) NULL    # 軟刪除時間；非空 → 顯示佔位、content 清成 ""

Reaction（新表）
  id (PK, Uuid)
  message_id (FK→Message, ondelete CASCADE)
  user_id (FK→User, ondelete CASCADE)
  emoji      String(16)
  created_at DateTime(tz)
  UNIQUE(message_id, user_id, emoji)   # 同人對同訊息同 emoji 只算一次
```

- **固定表情組白名單**：`👍 ❤️ 😂 😮 😢 🙏`。後端常數 `QUICK_REACTIONS`（Python）；前端同一份常數於 `frontend/contracts/index.ts` 匯出（小量刻意重複，兩端各一份）。`react` 帶非白名單 emoji → error。
- **動作語意**：
  - 編輯：覆蓋 `content`、設 `edited_at = now()`。不留歷史、不限時間。已刪除訊息不可編輯。
  - 刪除：設 `deleted_at = now()`、`content = ""`。佔位顯示「此訊息已刪除」；其附件與表情在輸出時一律不顯示。
  - 表情：toggle —— (user, message, emoji) 不存在則新增、存在則刪除。

### `MessageOut` 新增欄位

```
edited_at: datetime | null
deleted: bool                                  # = deleted_at 非空
reactions: [ { emoji: str, count: int, user_ids: list[str] } ]
```

- **reactions 形狀與觀看者無關**（不含 `reacted_by_me`）。原因：同一個 `message_updated` 廣播給多位成員，無法把某人的「我按過沒」烤進 payload。前端用 `currentUser.id ∈ user_ids` 自行判定。REST 歷史與 WS 序列化用同一形狀。
- `deleted` 訊息：`content` 一律回 `""`、`attachment` 回 `null`、`reactions` 回 `[]`、`edited_at` 照實（通常 null）。

## 4. WebSocket：`/ws`

### Client → Server（新增）

```
{type:"edit",   message_id, content}
{type:"delete", message_id}
{type:"react",  message_id, emoji}
```

### Server → Client（新增）

```
{type:"message_updated", message}    # 完整 MessageOut，廣播給對話所有在線成員（含操作者）
```

動作對象是既有訊息（已有真實 id），故**不需要 ack/temp_id**；失敗回 `{type:"error", reason}`。

### 各動作流程與驗證

```
edit:
  1. 解析 message_id；查 Message
  2. 驗 message.sender_id == user 且 deleted_at IS NULL 且 content 非空
     否則 {type:"error", reason:"forbidden"|"invalid_payload"}
  3. message.content = content；message.edited_at = now()；commit
  4. 廣播 message_updated（完整序列化）給該對話所有在線成員

delete:
  1. 查 Message；驗 sender_id == user（已刪除 → 直接回現狀，不重複處理）
  2. deleted_at = now()；content = ""；commit
  3. 廣播 message_updated

react:
  1. 查 Message；驗 user 是該對話成員（get_conversation_for_member）
  2. 驗 emoji ∈ QUICK_REACTIONS，否則 {type:"error", reason:"invalid_reaction"}
  3. toggle：查 (message_id, user_id, emoji)；有則 delete、無則 insert；commit
  4. 廣播 message_updated
```

- 序列化（`_serialize_message` 與 REST `MessageOut`）統一加上 `edited_at` / `deleted` / `reactions`。reactions 由 `Reaction` 依 emoji 聚合（`count` 與 `user_ids`）。
- 既有 `ack` / `message` / `read` / 群組廣播路徑不變。

## 5. 前端（微前端）

### 契約 `frontend/contracts/index.ts`

```ts
export interface ReactionGroup { emoji: string; count: number; user_ids: string[] }

export interface Message {            // 既有欄位不變，新增：
  edited_at: string | null;
  deleted: boolean;
  reactions: ReactionGroup[];
}

// ClientWsMessage 新增三變體：
| { type: 'edit'; message_id: string; content: string }
| { type: 'delete'; message_id: string }
| { type: 'react'; message_id: string; emoji: string }

// ServerWsMessage 新增：
| { type: 'message_updated'; message: Message }

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];
```

### chat remote

- `messageStore.ts`：`applyMessageUpdate(list, message): ChatMessage[]` —— 依 `id` 取代該則（保留 `status: 'sent'`；找不到則回原清單不動）。`makeOptimistic` 補 `edited_at: null, deleted: false, reactions: []`。其餘函式因 `ChatMessage extends Message` 自動相容。
- `store.ts`：action `updateMessage(message: Message)` —— 用 `message.conversation_id` 找清單、套 `applyMessageUpdate`。
- `ChatApp.tsx`：`handleServerMessage` 新增 `case 'message_updated'` → `useChatStore.getState().updateMessage(msg.message)`；新增 `editMessage(id, content)` / `deleteMessage(id)` / `toggleReaction(id, emoji)`（各 `socketRef.current?.send` 對應類型），傳給 `Thread`。
- `components/Thread.tsx`（`MessageBubble`）：
  - **已刪除**（`message.deleted`）→ 斜體灰字「此訊息已刪除」佔位；不顯示內容/附件/表情/編輯刪除鈕。
  - **已編輯**（`message.edited_at`）→ 狀態列旁顯示「已編輯」。
  - **表情列**：泡泡下方顯示各 `ReactionGroup` chip「{emoji} {count}」；`currentUserId ∈ user_ids` 時高亮；點擊呼叫 `onReact(messageId, emoji)` toggle。另有「＋」鈕展開 `QUICK_REACTIONS` 6 個 emoji，點選 toggle。
  - **自己的訊息**（`sender_id === currentUserId` 且未刪除）：小「編輯 / 刪除」鈕。編輯 → 行內輸入框（預填 `content` + 儲存/取消），儲存呼叫 `onEdit(messageId, newContent)`；刪除 → 呼叫 `onDelete(messageId)`。
  - 新 props：`onEdit: (id, content) => void`、`onDelete: (id) => void`、`onReact: (id, emoji) => void`。

### shell

不動。

## 6. 測試策略

### 後端（pytest）

- 編輯：限本人（非本人 → forbidden）、標記 `edited_at`、廣播 `message_updated`；不可編輯已刪除；空 content → invalid_payload。
- 刪除：限本人、軟刪（`deleted` true、`content` 清空）、廣播。
- 表情：toggle 加/移除；限對話成員（非成員 → forbidden）；非白名單 emoji → invalid_reaction；聚合 `count` 與 `user_ids` 正確。
- `MessageOut`：歷史 API 反映 `edited_at` / `deleted` / `reactions`；已刪除訊息 content="" 且 reactions=[]。

### 前端（Vitest）

- `messageStore.applyMessageUpdate`：依 id 取代、找不到不動。
- `store.updateMessage`：套用到正確對話。
- `MessageBubble`：渲染「已編輯」標記、刪除佔位文字、表情 chip（含 `currentUserId` 高亮）；點 chip / 快速 emoji 呼叫 `onReact`；自己訊息的編輯送出呼叫 `onEdit`、刪除呼叫 `onDelete`。

## 7. 安全與備註

- 編輯/刪除嚴格限 `sender_id == user`；表情限對話成員 —— 皆以既有 `get_conversation_for_member` 為基礎，404/forbidden 不洩漏存在性。
- emoji 白名單於後端強制，避免任意字串塞入。
- `Reaction` 的 `UNIQUE(message_id, user_id, emoji)` 防重複；toggle 以查詢後增刪實作。
- 已刪除訊息在所有輸出端點一律遮蔽 content/attachment/reactions，避免外洩已刪內容。
- 反應頻繁時每次廣播整則訊息略重，MVP 可接受；未來可改為差量事件。
