# 群組聊天 — 設計文件

- 日期：2026-06-19
- 狀態：設計定案，待 review
- 範圍：在現有 1對1 MVP 上新增「最小可用」群組聊天
- 前置：本功能原列於 [MVP 設計文件](../2026-06-19-chat-web-mvp-design.md) 的「明確不做」，現經使用者要求納入。

## 1. 目標與範圍

把現有「兩人制」聊天一般化為「N 人對話」，讓使用者能建立群組並即時群聊。

### 驗收範圍（最小可用）

- ✅ 建立群組（命名 + 從好友清單選成員）
- ✅ 群組內 1對多即時文字收發（WebSocket）
- ✅ 看得到群組成員
- ✅ 每則訊息顯示「已讀 N」（被幾人讀過）
- ✅ 群組未讀數
- ✅ 1對1 既有功能維持不變（回歸）

### 明確不做（之後擴充）

- ✅ ~~建群後加入 / 移除成員、退出群組~~ —— 已於 2026-06-21 實作，見 [群組管理設計](../group-management/spec.md)。
- ✅ ~~群組改名 / 設定~~ —— 已於 2026-06-21 實作，見 [群組管理設計](../group-management/spec.md)。
- ✅ ~~管理員角色 / 權限~~ —— 已於 2026-06-21 實作，見 [群組管理設計](../group-management/spec.md)。
- ✅ ~~用 email 加非好友進群（只能加好友）~~ —— 已於 2026-06-21 實作，見 [群組管理設計](../group-management/spec.md)。

## 2. 核心決策

採**統一資料模型**：1對1 與群組共用同一組表，差別只在成員數與 `type`。
WS 推播、未讀計算、訊息清單全部走「查成員 → 逐一處理」一條程式路徑，避免兩套重複邏輯。

替代方案（群組另開 `Group*` 系列表、複製 REST/WS 邏輯）已否決：短期快但兩條路徑、重複碼多、總工時更高。

## 3. 資料模型（SQLAlchemy）

```
Conversation
  id (PK)
  type           'direct' | 'group'
  name           群組名稱（group 才有；direct 為 NULL）
  creator_id     建立者 user_id（group 才有意義；FK→User，nullable）
  direct_key     direct 對話的正規化唯一鍵（group 為 NULL）
  created_at
  UNIQUE(direct_key)          # 保證同兩人只有一筆 direct 對話

ConversationMember           # 對話成員：direct=2 筆，group=N 筆
  id (PK)
  conversation_id (FK→Conversation, ondelete CASCADE)
  user_id (FK→User, ondelete CASCADE)
  created_at
  UNIQUE(conversation_id, user_id)

Message                      # 不再有 read_at
  id (PK)
  conversation_id (FK→Conversation, ondelete CASCADE)
  sender_id (FK→User)
  content (text)
  created_at

MessageRead                  # 已讀紀錄：誰讀了哪一則
  id (PK)
  message_id (FK→Message, ondelete CASCADE)
  user_id (FK→User, ondelete CASCADE)
  read_at
  UNIQUE(message_id, user_id)
```

### 衍生計算定義

- **direct「已讀」**：該訊息存在「對方」的 `MessageRead` → 顯示「已讀」。
- **group「已讀 N」**：該訊息的 `MessageRead` 筆數（排除寄件人本人）。
- **某對話「我的未讀數」**：此對話中 `sender_id != 我` 且我無 `MessageRead` 的訊息數。
- **direct 唯一性**：`direct_key = "<min(uid)>:<max(uid)>"`（字串比較排序兩個 user_id）。`get_or_create_conversation` 先以 `direct_key` 查，找不到才建。取代原本的 `user_a_id < user_b_id` 欄位約束。

## 4. REST API

`/auth`、`/users/me`、`/contacts` 不變。

| Method | 路徑 | 說明 |
|---|---|---|
| GET | `/conversations` | direct + group 混合清單（見新外型） |
| POST | `/conversations/groups` | 建群組 `{name, member_user_ids:[...]}` |
| GET | `/conversations/{id}/messages?before=&limit=` | 歷史訊息；每則帶 `read_count`，權限改判「我是否為成員」 |

### 回應外型

```
ConversationOut
  id
  type            'direct' | 'group'
  name            group 才有；direct 為 null
  other_user      direct 才有（對方 UserOut）；group 為 null
  members         成員 UserOut 陣列
  last_message    MessageOut | null
  unread_count    此對話我的未讀數

MessageOut
  id, conversation_id, sender_id, content, created_at
  read_count      讀過此則的人數（排除寄件人）
```

### 建群組驗證（POST /conversations/groups）

- `name` 非空（Pydantic min_length=1）。
- `member_user_ids`：每個都必須是 current_user 的好友，否則 `400`；去重後 ≥ 1 人。
- 建立者自動加入成員。建立 `type='group'` 的 Conversation 與對應 ConversationMember，回傳 `ConversationOut`。

### 標記已讀

維持走 WebSocket（見 §5），REST 不另開端點；歷史 API 僅回傳當下 `read_count`。

## 5. WebSocket：`/ws`

訊息類型不變（Client：`message`/`read`/`typing`；Server：`ack`/`message`/`read`/`error`），改的是內部「推給誰」與已讀計算。

### 送訊息（`message`）

```
1. 驗 sender 是該對話的成員（查 ConversationMember）
2. 寫 Message → 回 ACK 給寄件人（含 temp_id）
3. 推播：查該對話「其他所有成員」→ 對每個在線者推 {type:"message", message}
   離線者不推，靠 REST 補（與 1對1 相同）
```

### 已讀（`read`）

```
1. 驗 current_user 是成員
2. 對「此對話中 sender != 我、且我尚無 MessageRead」的訊息，批次 insert MessageRead，
   收集這批 message_ids
3. 通知其他在線成員：{type:"read", conversation_id, reader_id, message_ids:[...]}
```

### 協定型別調整

`ServerWsMessage` 的 `read` 事件**新增 `message_ids: string[]`**：直接告訴前端「這些訊息被這位 reader 讀了」，前端對這些訊息 `read_count + 1`，不需前端自行推斷。`ConnectionManager`（`user_id → set[WebSocket]`）本身無需改動。

## 6. 前端（微前端）

### 契約 `frontend/contracts/index.ts`（兩端共用，先改）

- `Conversation`：加 `type`、`name: string | null`、`members: CurrentUser[]`；`other_user` 改為可 null。
- `Message`：`read_at` → `read_count: number`。
- `ServerWsMessage` 的 `read`：加 `message_ids: string[]`。
- 新增建群組 request 型別（`{ name: string; member_user_ids: string[] }`）。

### chat remote

- `api.ts`：新增 `createGroup(name, memberUserIds)`；`listMessages` 回傳含 `read_count`。
- `messageStore.ts`：`ChatMessage` 改用 `read_count`；新增處理 read 事件 → 對 `message_ids` 內訊息 `read_count + 1`（取代原依 `read_at` 的邏輯）。
- `components/Sidebar.tsx`：
  - 清單同時顯示 direct（對方名字）與 group（群組名 + 成員數，如「家族群 · 3 人」）。
  - 新增「＋ 新群組」按鈕 → 內嵌面板：群組名輸入 + 好友勾選清單 + 建立。
- `components/Thread.tsx`：
  - 標題：direct 顯示對方名字；group 顯示群組名（附成員數）。
  - 群組訊息顯示**寄件人名字**（非自己訊息上方一行小字）；direct 不顯示。
  - 我方訊息狀態：direct 維持「已讀／已送出」；group 顯示「已讀 {read_count}」（0 則顯示已送出）。
- `ChatApp.tsx`：處理帶 `message_ids` 的 read 事件；接 `createGroup` 流程；新建群組後自動開啟。

### shell

不動。群組不影響 host／remote 邊界，shell 只是繼續把 `token`/`currentUser` 傳給 chat。

UI 取捨：建群組用 Sidebar 內嵌面板，不另開路由或彈窗元件。

## 7. 資料遷移（Alembic 0002）

- 建 `conversation_members`、`message_reads` 表。
- `conversations` 加 `type`（預設 `'direct'`）、`name`、`creator_id`、`direct_key` + `UNIQUE(direct_key)`。
- 資料搬移：
  - 每筆既有對話 → 寫 2 筆 ConversationMember（原 `user_a_id`、`user_b_id`）、`type='direct'`、計算 `direct_key`。
  - 每筆 `Message.read_at` 非空 → 寫一筆 `MessageRead`（reader = 該訊息的非寄件人成員、`read_at` 沿用）。
- 移除 `conversations.user_a_id/user_b_id` 與舊 UNIQUE、`messages.read_at`。
- **SQLite 限制**：drop column 須用 `op.batch_alter_table`（批次模式），否則本機／測試的 SQLite 會失敗。
- 既有 `backend/dev.db` 需 `alembic upgrade head`；測試用 `Base.metadata.create_all` 直接取得新 schema。

## 8. 測試策略

### 後端（pytest）

- 回歸：既有 `read_at` 斷言改為 `read_count` / `MessageRead`，確認 1對1 仍正常。
- 新增：
  - 建群組：非好友成員 → 400、`name` 空 → 422、去重後成員 < 1 → 400、成功回 `ConversationOut`。
  - 群組送訊息：WS 推給**多個**在線成員（用多個 TestClient 連線驗證）。
  - 群組「已讀 N」：多人讀後 `read_count` 正確。
  - 群組未讀數計算。

### 前端（Vitest）

- `messageStore`：read 事件帶 `message_ids` → 對應訊息 `read_count + 1`。
- `Thread`：群組顯示寄件人名字 + 「已讀 N」；direct 維持原樣。
- `api.createGroup`。

## 9. 風險與備註

- 本變更動到既有 1對1 的核心（對話建立、已讀、WS 推播），務必保留回歸測試綠燈。
- `direct_key` 取代欄位約束後，所有建立 direct 對話的路徑都必須經 `get_or_create_conversation`，不可繞過。
- 多 worker / 水平擴充時，`ConnectionManager` 的記憶體在線狀態仍是單機限制（與原設計相同，超出本次範圍）。
