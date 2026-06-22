# 站內通知(in-app notifications)— Spec

- 日期：2026-06-22
- 狀態：待核可(approval gate)
- 分支：`feat/in-app-notifications`(疊在 `feat/group-chat` 之上)
- 前置：message-actions 設計把「表情回應的通知」明確列為「另一子專案（需新建 in-app 通知面）」,本功能即是。

## Overview

讓使用者收到「**別人對你的訊息做了什麼**」的站內通知:被回覆(reply)、被按表情(reaction)、被轉發(forward)。通知持久化於新 `Notification` 表,有未讀/已讀狀態;前端在 chat remote 提供鈴鐺 🔔 + 未讀紅點 + 下拉通知中心。**開啟「該訊息所在的對話」即把指向它的通知標為已讀**。即時推播沿用現有 WebSocket;歷史/未讀數走 REST。

## Business Requirements

- BR-1：使用者能得知自己的訊息被他人 reply / reaction / forward,不必逐一對話翻找。
- BR-2：通知需在重整 / 重新登入後仍存在(持久化),並反映未讀數。
- BR-3：離線期間發生的互動,上線後要補得回來(不漏)。
- BR-4：不打擾使用者自己的動作(對自己的訊息互動不產生通知)。
- BR-5：維持微前端邊界 —— 通知屬 chat 領域,shell(host)不變。

## Functional Requirements

- FR-1：以下事件各產生一筆通知,收件人為「被互動訊息的 sender」:
  - reply：他人送出帶 `reply_to_message_id` 的訊息,指向你的訊息。
  - reaction：他人對你的訊息「加上」表情(toggle 移除不產生、也不刪既有通知)。
  - forward：他人轉發你的訊息(原作者 = 你)。
- FR-2：`actor_id == user_id`(對自己的訊息互動)時不建立通知。
- FR-3：一事件一通知(不合併);reaction 帶該 emoji。
- FR-4：建立通知後,收件人若在線,透過 WS 立即推播 `{type:'notification', notification}`。
- FR-5：REST 提供分頁通知列表(新→舊)與未讀數。
- FR-6：開啟某對話時,該對話下所有未讀通知一律標為已讀(`read_at = now`)。開啟通知中心本身**不**標已讀。
- FR-7：點擊一筆通知 → 導向 `conversation_id` 對應對話(隨即因 FR-6 標已讀)。

## Acceptance Criteria

- AC-1：A 回覆 B 的訊息 → B 得到一筆 type=reply 通知(actor=A、message=B 的原訊息、conversation=該對話)。
- AC-2：A 對 B 的訊息加 👍 → B 得到 type=reaction、emoji=👍 通知;A 再按一次(移除)→ 不新增、也不刪除既有通知。
- AC-3：A 轉發 B 的訊息到別的對話 → B 得到 type=forward 通知(conversation = B 原訊息所在對話)。
- AC-4：對自己的訊息 reply/react/forward → 不產生通知。
- AC-5：收件人在線 → 立即收到 WS `notification`;離線 → 不推,但 `GET /notifications` 撈得到且計入未讀。
- AC-6：開啟通知對應的對話 → 該對話通知 `read_at` 被填、未讀數下降;開通知中心不改已讀。
- AC-7：未讀數 = 該使用者 `read_at IS NULL` 的通知數。

## Edge Cases

- EC-1：被互動的訊息事後被軟刪 → 通知仍在,點擊照常開對話(訊息顯示佔位)。
- EC-2：reaction toggle off → 不刪通知(可能留下「X 按過表情」但已收回,可接受,YAGNI)。
- EC-3：群組內的 reply/react/forward → 收件人一律是該訊息 sender,與群組型別無關。
- EC-4：同一則訊息被多人或多次互動 → 各自獨立通知(不聚合)。
- EC-5：使用者多裝置/多連線在線 → WS 推播送給其所有連線(沿用 `ConnectionManager`)。
- EC-6：建立通知與廣播訊息在同一個 WS handler 內,須避免額外 N+1 與跨 session 物件存取問題(序列化只讀已載入欄位)。

## API Contracts

### REST

```
GET /notifications?before=<ISO8601>&limit=<1..50>
  200 → { items: NotificationOut[], unread_count: int }
        # items 依 created_at 新→舊;before 為游標(取 created_at < before)
        # unread_count 一併回傳,省一支 API

POST /notifications/read
  body: { conversation_id: uuid }
  200 → { ok: true, marked: int }   # 將該對話下 read_at IS NULL 的通知標已讀
```

`NotificationOut`:
```
{
  id: uuid
  type: 'reply' | 'reaction' | 'forward'
  actor: { id: uuid, display_name: str }
  conversation_id: uuid
  message_id: uuid
  message_preview: str        # 被互動訊息的內容摘要(已刪→"")
  emoji: str | null           # 僅 reaction
  read: bool                  # = read_at 非空
  created_at: datetime
}
```

### WebSocket(server → client,新增)

```
{ type: 'notification', notification: NotificationOut }
# 建立通知當下、收件人在線才推。無 client→server 新類型(已讀走 REST)。
```

## Data Model Changes

新表 `Notification`(migration `0009`):

```
Notification
  id              Uuid PK
  user_id         Uuid FK→users.id        ondelete CASCADE  # 收件人
  type            String(16)              # 'reply'|'reaction'|'forward'
  actor_id        Uuid FK→users.id        ondelete CASCADE
  conversation_id Uuid FK→conversations.id ondelete CASCADE
  message_id      Uuid FK→messages.id     ondelete CASCADE
  emoji           String(16) NULL
  read_at         DateTime(tz) NULL
  created_at      DateTime(tz) server_default=now
```

- 索引:`ix_notifications_user_created`(user_id, created_at desc)供列表分頁;未讀數以 `user_id + read_at IS NULL` 查詢。
- 既有表不變。

## State Changes

### 後端
- WS handler(`_handle_message` reply 分支 / `_handle_react` 加表情 / `_handle_forward`)在既有 commit 流程內,額外建立 `Notification` 並於收件人在線時推播。
- 新增 `app/services/notifications.py`(建立 + 序列化 + 標已讀 + 查詢的集中邏輯),WS 與 REST 共用。

### 前端(chat remote)
- `store`:新增 `notifications: NotificationOut[]`、`unreadCount: number`;action `addNotification`(WS 進來 upsert,unread+1)、`setNotifications`(REST 載入)、`markConversationRead(conversationId)`(把該對話通知 read=true、重算 unread)。
- `selectConversation` 開對話時呼叫 `api.markNotificationsRead(conversationId)` 並 `markConversationRead`。
- shell:不變。

## UI Behaviour

- chat remote 的 Sidebar header 放一個鈴鐺 🔔,右上角顯示未讀紅點數(>9 顯示 9+)。
- 點鈴鐺開下拉 `NotificationCenter`:列出通知(新→舊),每筆顯示 actor 名 + 動作文案(「回覆了你」/「對你的訊息按了 👍」/「轉發了你的訊息」)+ 訊息摘要 + 相對時間;未讀者左側有小圓點。
- 點一筆通知 → 關閉下拉 + `selectConversation(conversation_id)`(隨即標已讀、紅點下降)。
- 開下拉本身不標已讀。空狀態顯示「目前沒有通知」。

## Non-Functional Requirements

- NFR-1(效能):列表分頁(limit ≤ 50)、未讀數走索引查詢;通知建立不可在訊息送達熱路徑引入 N+1(序列化只讀已載入欄位,actor/preview 以單次查詢取得)。
- NFR-2(安全):所有 REST/WS 皆驗 JWT;`GET/POST /notifications` 僅能存取自己的(以 `user_id == current_user`),不洩漏他人存在性。
- NFR-3(一致性):通知建立與其觸發訊息在同一 DB transaction 內 commit,避免「訊息成功但通知遺失」或反之。
- NFR-4(相容):新表透過 SQLAlchemy 2.0 通用 `Uuid`、`DateTime(timezone=True)`,SQLite(測試)與 Postgres(正式)皆可。datetime 一律 tz-aware 比較(見專案既有 Postgres/SQLite tz 陷阱)。
```
