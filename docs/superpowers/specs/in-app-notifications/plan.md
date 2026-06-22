# 站內通知 — 實作計畫(plan)

對應 [spec.md](spec.md) 與 [bdd.feature](bdd.feature)。

## Architecture

通知建立**寄生在現有 WS handler 的既有 transaction 內**(reply 在 `_handle_message`、reaction 在 `_handle_react` 加表情分支、forward 在 `_handle_forward`),確保「觸發訊息成功 ⇔ 通知成功」原子性。建立後若收件人在線,沿用 `ConnectionManager` 推 `notification`。歷史與未讀走新 REST router。集中邏輯放 `app/services/notifications.py`,被 WS 與 REST 共用,避免散落。前端全在 chat remote:store 持有 `notifications`/`unreadCount`,`NotificationCenter` 呈現,`selectConversation` 觸發標已讀。shell 不動。

## Backend Changes

- `app/models/notification.py`:新增 `Notification` model(欄位見 spec)。
- `alembic/versions/0009_notifications.py`:建表 + 索引(無回填,新表)。
- `app/services/notifications.py`:
  - `create_notification(db, *, user_id, type, actor_id, conversation_id, message_id, emoji=None)`:`user_id == actor_id` 直接回 None(不建)。
  - `serialize_notification(db, n) -> dict`:組 actor 名與 message_preview(被互動訊息已刪 → "")。
  - `list_notifications(db, user_id, before, limit)` / `unread_count(db, user_id)`。
  - `mark_conversation_read(db, user_id, conversation_id) -> int`:回標記筆數。
- `app/ws/router.py`:三個 handler 在 commit 前 `create_notification(...)`;commit 後若 `manager.is_online(recipient)` → 推 `{type:"notification", notification: serialize_notification(...)}`。序列化所需資料在 session 內先取好(避免跨 session lazy-load)。
- `app/routers/notifications.py`:`GET /notifications`、`POST /notifications/read`;掛進 `app/main.py`。
- `app/schemas.py`:`NotificationOut`、`NotificationListOut{items, unread_count}`、`MarkReadRequest{conversation_id}`。

## Frontend Changes(chat remote)

- `frontend/contracts/index.ts`:`Notification`/`NotificationType` 型別、`ServerWsMessage` 加 `{type:'notification', notification}`。
- `frontend/chat/src/api.ts`:`listNotifications(before?, limit?)`、`markNotificationsRead(conversationId)`。
- `frontend/chat/src/store.ts`:`notifications`、`unreadCount`;`setNotifications`、`addNotification`、`markConversationRead`。
- `frontend/chat/src/notifications.ts`(純函式):`applyMarkRead(list, conversationId)`、`countUnread(list)`、動作文案 `describeNotification(n)` —— 與 React 解耦、可單測(沿用 messageStore 的純函式慣例)。
- `frontend/chat/src/components/NotificationCenter.tsx`:鈴鐺 + 未讀紅點 + 下拉列表 + 點擊導航。
- `frontend/chat/src/ChatApp.tsx`:`handleServerMessage` 加 `case 'notification'`;掛載時 `listNotifications` 灌 store;`selectConversation` 內呼叫 markRead;把鈴鐺接到 Sidebar header（傳 props）。
- `frontend/chat/src/components/Sidebar.tsx`:header 容納 `NotificationCenter`(以 prop 注入,維持元件可測)。

## Database Changes

- 新表 `notifications`(migration 0009),含 `ix_notifications_user_created`(user_id, created_at)。
- 無資料回填、不動既有表。SQLite/Postgres 皆相容(`Uuid`、`DateTime(timezone=True)`)。

## API Changes

- `GET /notifications?before=&limit=` → `{items, unread_count}`。
- `POST /notifications/read {conversation_id}` → `{ok, marked}`。
- WS 新增 server→client `notification`(無新 client→server 類型)。

## State Management Changes

- store 新欄位 `notifications`/`unreadCount`;三個 action。
- 已讀來源唯一:開啟對話 → `markNotificationsRead` REST + `markConversationRead` 本地。WS `notification` 進來 → `addNotification`(unread+1)。

## File Changes

新增:
- `backend/app/models/notification.py`
- `backend/alembic/versions/0009_notifications.py`
- `backend/app/services/notifications.py`
- `backend/app/routers/notifications.py`
- `backend/tests/test_notifications.py`
- `frontend/chat/src/notifications.ts`
- `frontend/chat/src/notifications.test.ts`
- `frontend/chat/src/components/NotificationCenter.tsx`
- `frontend/chat/src/components/NotificationCenter.test.tsx`
- `e2e/tests/notifications-api.spec.ts`(REST+WS)
- `e2e/tests/notifications-ui.spec.ts`(鈴鐺紅點 + 點擊導航,沿用 retryAction)

修改:
- `backend/app/ws/router.py`、`backend/app/main.py`、`backend/app/schemas.py`
- `frontend/contracts/index.ts`、`frontend/chat/src/{api,store,ChatApp}.ts(x)`、`frontend/chat/src/components/Sidebar.tsx`
- `frontend/chat/src/remotes.d.ts`(若 props 介面有變)
- `e2e/tests/helpers.ts`(視需要加 notification 相關 helper)

## Risks

- R-1:在訊息熱路徑建立通知 → 多一次 insert/查詢。緩解:序列化只讀已載入欄位、actor/preview 單次查詢;量大可日後改非同步。
- R-2:跨 session lazy-load(WS handler 在 commit 後序列化)→ 沿用既有 `_serialize_message` 模式,在 session 內先取齊欄位。
- R-3:tz-aware 比較(Postgres)→ 一律 `DateTime(timezone=True)` + aware 比較(專案既有陷阱,已有前例)。
- R-4:dev StrictMode 下 WS `send()`/接收時序 → 影響 UI E2E,沿用 `retryAction` 模式。
- R-5:reaction toggle 不刪通知會留下「過期」通知 → 已於 spec 接受(YAGNI),文案不宣稱「現在」狀態。

## Implementation Order

依 tasks.md:1 模型+遷移 → 2 service → 3 WS 觸發+推播 → 4 REST → 5 contracts+store+純函式 → 6 NotificationCenter+ChatApp 接線 → 7 E2E(API+UI)+文件。每個 task 走 TDD、可獨立 review。
