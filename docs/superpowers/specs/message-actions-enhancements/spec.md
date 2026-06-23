# 訊息動作小增強 — 設計文件（編輯歷史 / 編輯時限 / 自由 emoji / 還原刪除）

- 日期：2026-06-21
- 狀態：設計定案，待 review
- 範圍：在 [訊息編輯/刪除/表情回應](../message-actions/spec.md) 之上補三項小增強
- 前置：原列於該文件「明確不做（之後擴充）」。建立在 `feat/message-actions` 分支之上。

## 1. 目標與範圍

把訊息動作的三項延伸補齊，全部沿用既有 edit/delete/react 模型與 WebSocket 廣播：

- ✅ 編輯歷史 / 版本紀錄（完整：新表存每次編輯前內容，可點開看各版本）
- ✅ 編輯時間限制（送出後 15 分鐘內可編輯）
- ✅ 自由 emoji 選擇器（保留快速 6 個 + 「＋」開 emoji-mart 完整選擇器）
- ✅ 還原已刪除訊息（只寄件人，刪除後 5 分鐘內可還原）

### 明確不做（屬其他子專案）

- ❌ 對訊息回覆（reply / thread）、轉發 —— 另一子專案
- ❌ 表情回應的通知 —— 另一子專案（需新建 in-app 通知面）
- ❌ 編輯歷史的 diff 視覺化（只逐版列出全文）
- ❌ 還原已過時窗的訊息、管理員代為還原

## 2. 核心決策

架構沿用上一份 spec 的**方案 A：WebSocket 協定 + 單一 `message_updated` 廣播**，三項皆為其延伸，不重新評估 REST-vs-WS。

唯一新的架構取捨：**編輯歷史採 on-demand REST 端點**（點「已編輯」才抓），而非把整包版本陣列烤進每個 `MessageOut`。原因：絕大多數訊息沒人看歷史，把歷史塞進每次廣播/分頁過重。替代方案（歷史內嵌 `MessageOut`）已否決。

新的 client→server 類型只有一種 `restore`；編輯、還原、表情變更全部復用既有 `message_updated` 事件。

## 3. 資料模型（SQLAlchemy）

### 新表 `MessageEdit`（版本紀錄）

```
MessageEdit
  id          PK Uuid
  message_id  FK→Message (ondelete CASCADE)
  content     Text           # 某個「過去版本」的內容
  created_at  DateTime(tz)   # 那個版本被寫下的時間（原始送出時間，或更早一次編輯的時間）
```

編輯時：把「目前 content + 它的生效時間」快照進 `MessageEdit`，再覆寫成新內容。

```
prev_at = message.edited_at or message.created_at   # 目前版本是何時寫的
insert MessageEdit(message_id, content=message.content, created_at=prev_at)
message.content = 新內容
message.edited_at = now()
```

→ 歷史 = `MessageEdit` 各列（舊版本 + 寫下時間）依 `created_at` 排序 **＋** 目前的 `message.content`（配 `message.edited_at`）當最後一筆。自然呈現「10:00 這版 / 10:05 這版 / 目前 10:10」。`edited_at` 欄位已存在，編輯歷史不需動 `Message` 其他欄位。

### `Message` 刪除語意變更（為了還原）

- 現況刪除把 DB 的 `content` 清成 `""`（破壞性）。**改為：刪除只設 `deleted_at`，DB 保留原 content**。
- 輸出層（`_serialize_message` / `MessageOut`）維持「`deleted` 時 content 回 `""`、attachment 回 `null`、reactions 回 `[]`」的遮蔽（這層已存在）。
- 還原時原文還在，清掉 `deleted_at` 即重現。

### `MessageOut` 新增 `deleted_at`

```
deleted_at: datetime | null     # 已刪才有值；前端據此算 5 分鐘還原時窗
```

只在已刪訊息有值，不洩漏內容（content 仍遮蔽為 `""`）。

### 時窗常數（非欄位，純運算）

- `EDIT_WINDOW = timedelta(minutes=15)`（以 `message.created_at` 起算）
- `RESTORE_WINDOW = timedelta(minutes=5)`（以 `message.deleted_at` 起算）

### emoji 放寬

- `Reaction` 表不變（`emoji String(16)` 容得下多 codepoint emoji）。
- 後端拿掉 `QUICK_REACTIONS` 白名單強制，改驗「單一 emoji」：非空、≤ 8 Unicode codepoints、不含 ASCII 英數/空白字元（避免任意文字被塞成 reaction）。
- 前端 `QUICK_REACTIONS` 6 個保留作快速列。

### Migration

- 一支 Alembic migration：建 `MessageEdit` 表 + 為 `messages` 加 `deleted_at`？——`deleted_at` 已於 message-actions 既有（見前一份 spec 第 3 節），故 **僅新建 `MessageEdit` 表**。
- 刪除語意改變（不清空 content）是行為調整，不需 migration。

## 4. WebSocket `/ws` 與 REST

### Client → Server（新增一種）

```
{type:"restore", message_id}      # 還原已刪除訊息
```

`edit` / `delete` / `react` 沿用；`edit`、`delete`、`react` 的驗證/行為調整見下。

### Server → Client

不新增事件。編輯、還原、表情變更全部復用 `{type:"message_updated", message}`（完整 MessageOut，廣播給對話所有在線成員，含操作者）。

### 各動作流程

```
edit:
  1. 查 Message;驗 sender_id == user、deleted_at IS NULL、content 非空
     否則 error reason:"forbidden" | "invalid_payload"
  2. ★新增:now() - created_at > EDIT_WINDOW(15min) → error reason:"edit_window_passed"
  3. 快照舊版本進 MessageEdit;覆寫 content;edited_at = now();commit
  4. 廣播 message_updated

delete:
  1. 查 Message;驗 sender_id == user(已刪 → 回現狀)
  2. ★改:只設 deleted_at = now()(不再清空 content);commit
  3. 廣播 message_updated

restore:（★新）
  1. 查 Message;驗 sender_id == user、deleted_at IS NOT NULL
     否則 error reason:"forbidden"
  2. now() - deleted_at > RESTORE_WINDOW(5min) → error reason:"restore_window_passed"
  3. deleted_at = NULL;commit(content 原文還在,直接重現)
  4. 廣播 message_updated

react:
  1. 查 Message;驗 user 是對話成員(get_conversation_for_member)
  2. ★改:驗 emoji 為「單一 emoji」(非空、≤8 codepoints、無 ASCII 英數/空白)
     否則 error reason:"invalid_reaction"(拿掉白名單)
  3. toggle;commit;廣播 message_updated
```

### 新增 REST 端點（編輯歷史 on-demand）

```
GET /messages/{message_id}/edits
  權限:對話成員(get_conversation_for_member);非成員 / 不存在 → 404
  已刪除訊息 → 403 forbidden(比照 content 遮蔽,不外洩已刪內容)
  回傳:版本陣列(舊→新) + 目前版本當最後一筆
        [ { content: str, created_at: datetime }, ... ]
```

`_serialize_message` / `MessageOut` 形狀僅新增 `deleted_at`；deleted 訊息的 content 遮蔽改靠輸出層（DB 不再清空）。

## 5. 前端（微前端 chat remote）

### 契約 `frontend/contracts/index.ts`

```ts
// ClientWsMessage 新增:
| { type: 'restore'; message_id: string }

// 編輯歷史 REST 回傳型別:
export interface MessageVersion { content: string; created_at: string }

// Message 新增(對齊後端 MessageOut):
//   deleted_at: string | null

// 時窗常數(前端據此決定按鈕顯不顯示,與後端各一份,刻意小重複):
export const EDIT_WINDOW_MS = 15 * 60 * 1000;
export const RESTORE_WINDOW_MS = 5 * 60 * 1000;
// QUICK_REACTIONS 6 個保留
```

`ReactionGroup` / `message_updated` 形狀不動。

### 依賴

chat remote 加 `@emoji-mart/data` + `@emoji-mart/react`（只進 chat 包）。

### ApiClient `chat/src/api.ts`

- `getMessageEdits(messageId): Promise<MessageVersion[]>` —— `GET /messages/{id}/edits`，沿用既有 `ApiError`。

### `messageStore.ts`

- `makeOptimistic` 補 `deleted_at: null`。
- `applyMessageUpdate` 不變（還原/編輯/表情都是依 id upsert 的另一筆 `message_updated`）。

### `ChatApp.tsx` 接線

- 新增送出 helper `restoreMessage(id)`（`socketRef.current?.send({type:'restore',message_id:id})`），傳給 `Thread`。
- `handleServerMessage` 不動（`message_updated` 已處理還原/編輯/表情）。
- `editMessage` / `deleteMessage` / `toggleReaction` 已有，不動。

### `components/Thread.tsx`（MessageBubble）

- **編輯鈕**：`sender_id===currentUserId && !deleted && (now - created_at) < EDIT_WINDOW_MS` 才顯示。送出仍呼叫 `onEdit`；若伺服器回 `edit_window_passed`（臨界競態）→ 顯示錯誤、退出編輯框。
- **「已編輯」標記**：改為可點 → 開 `EditHistoryPopover`，內部 `getMessageEdits(id)` 抓版本陣列，逐版列「內容 + 時間」，最後一筆標「目前」。
- **刪除佔位**：`deleted` 時顯示「此訊息已刪除」；若 `sender_id===currentUserId && deleted_at && (now - deleted_at) < RESTORE_WINDOW_MS` 加「還原」鈕 → `onRestore(id)`。
- **表情 ＋ 鈕**：點開 emoji-mart Picker（浮層），選任一 emoji → `onReact(id, emoji)` toggle；快速 6 個列保留。
- 新 props：`onRestore: (id) => void`。

### 新元件

- `EditHistoryPopover.tsx`：抓並逐版列出歷史。
- emoji picker 浮層：包 emoji-mart `<Picker>`。

### shell

不動。

## 6. 測試策略

### 後端（pytest）

- **編輯歷史**：單次編輯建 1 筆 `MessageEdit`（快照舊內容 + 原時間）；多次編輯產生依時間排序的版本鏈；`GET /messages/{id}/edits` 回「各舊版 + 目前版」順序正確；非成員 → 404；已刪訊息 → 403。
- **編輯時限**：`created_at` 在 15 分鐘內可編輯；超過 → `edit_window_passed`（造超時：直接改 DB `created_at` 或 monkeypatch 時間）。
- **刪除/還原**：刪除後 DB 仍保有原 content（只 `deleted_at` 有值、輸出遮蔽 `""`）；寄件人 5 分鐘內 `restore` → `deleted` false、content 重現、廣播 `message_updated`；非寄件人 → `forbidden`；超過 5 分鐘 → `restore_window_passed`；對未刪訊息 restore → `forbidden`。
- **表情放寬**：白名單外單一 emoji（如 🎉）可加；含 ASCII 文字/過長 → `invalid_reaction`；聚合 `count`/`user_ids` 正確。
- **WS 廣播**：兩個 TestClient 連線，驗 restore 後雙方收到 `message_updated`（deleted=false）。

### 前端（Vitest + Testing Library）

- `api.getMessageEdits`：正確打 `GET /messages/{id}/edits`、解析版本陣列。
- `MessageBubble`：編輯鈕在 `created_at` 超過 15 分鐘時不出現；點「已編輯」開 `EditHistoryPopover` 並呼叫 `getMessageEdits` 渲染各版本；已刪 + 寄件人 + 5 分鐘內顯示「還原」鈕、點擊呼叫 `onRestore`，超時不顯示；表情 ＋ 開 picker、選 emoji 呼叫 `onReact`（emoji-mart 在 jsdom 以淺層 mock 或只驗 picker 觸發 callback）。
- `messageStore` / `store.updateMessage`：沿用既有，補一條還原情境（`deleted_at` 由值轉 null）的 upsert 斷言。

### E2E（手動，選配）

兩帳號跑「編輯→看歷史→超時不可編輯」「刪除→5 分鐘內還原」「按非標準 emoji」即時同步，如前幾個功能後補。自動化測試已涵蓋邏輯。

## 7. 安全與備註

- 編輯/還原嚴格限 `sender_id == user`；表情限對話成員 —— 皆以既有 `get_conversation_for_member` 為基礎，404/forbidden 不洩漏存在性。
- 編輯歷史端點對非成員 404、對已刪訊息 403，避免外洩已刪/他人對話內容。
- emoji 改白名單為「單一 emoji」形狀驗證，仍擋任意文字塞入。
- 刪除改為保留 content + 輸出遮蔽：已刪訊息在所有輸出端點（WS 廣播、REST 分頁、歷史端點）一律遮蔽 content/attachment/reactions，僅 5 分鐘內寄件人可還原重現。
- 還原時窗、編輯時窗皆於後端強制（前端時窗常數只控制按鈕顯隱，非安全邊界）。
