# 站內通知 — Tasks

每個 task 小、可獨立 review、可獨立測。對應 [plan.md](plan.md)、[bdd.feature](bdd.feature)。

## Task 1 — 資料模型 + 0009 遷移

Goal：新增 `Notification` model 與建表遷移。
Files：`backend/app/models/notification.py`、`backend/app/models/__init__.py`(若有匯總)、`backend/alembic/versions/0009_notifications.py`、`backend/tests/test_notifications.py`(遷移/建表 smoke)。
Acceptance Criteria：
- `Notification` 欄位齊全(spec 的 Data Model);`DateTime(timezone=True)`、通用 `Uuid`。
- 0009 在 SQLite 與(若可)Postgres 皆 `upgrade head` 成功,建出 `notifications` 表與 `ix_notifications_user_created`。
- conftest 的 `create_all` 後新表存在。

## Task 2 — notifications service(純後端邏輯)

Goal：集中建立 / 序列化 / 查詢 / 標已讀邏輯。
Files：`backend/app/services/notifications.py`、`backend/tests/test_notifications.py`。
Acceptance Criteria：
- `create_notification`:`user_id == actor_id` 回 None 不建;否則 insert 並回物件。
- `serialize_notification`:含 actor.display_name、message_preview(已刪訊息 → "")、emoji(僅 reaction)、read 旗標。
- `list_notifications`(新→舊、before 游標、limit)、`unread_count`、`mark_conversation_read`(回筆數)。
- 單元測試覆蓋:不通知自己、preview 遮蔽已刪、未讀數、標已讀只動該對話且只動自己的。

## Task 3 — WS 觸發 + 在線推播

Goal：reply / reaction(加) / forward 三處在既有 transaction 內建立通知,並對在線收件人推 `notification`。
Files：`backend/app/ws/router.py`、`backend/tests/test_notifications.py`(或 test_ws.py)。
Acceptance Criteria：
- reply(`_handle_message` 帶 reply_to)、reaction(`_handle_react` 僅「加」)、forward(`_handle_forward`)各建正確收件人/型別/emoji。
- toggle 移除表情不建、不刪(NB-07)。
- 收件人在線 → 收到 WS `{type:"notification", notification}`;離線 → 不推但已落庫(NB-14)。
- 與觸發訊息同一 commit;序列化不跨 session lazy-load。

## Task 4 — REST router

Goal：`GET /notifications`、`POST /notifications/read`。
Files：`backend/app/routers/notifications.py`、`backend/app/schemas.py`、`backend/app/main.py`、tests。
Acceptance Criteria：
- `GET` 回 `{items(新→舊、分頁), unread_count}`,只含自己的(NB-10)。
- `POST /notifications/read {conversation_id}` 標該對話自己的未讀 → `{ok, marked}`;對非自己對話 marked=0 不洩漏(NB-12);缺欄位 422(NB-13)。
- 未授權 401(NB-11)。

## Task 5 — contracts + store + 純函式

Goal：型別、WS 事件、store 狀態與純邏輯。
Files：`frontend/contracts/index.ts`、`frontend/chat/src/{api,store,notifications}.ts`、`frontend/chat/src/{store,notifications}.test.ts`、`frontend/chat/src/remotes.d.ts`(若需)。
Acceptance Criteria：
- `Notification` 型別 + `ServerWsMessage` 加 `notification`。
- `api.listNotifications` / `markNotificationsRead`。
- store:`notifications`/`unreadCount` + `setNotifications`/`addNotification`/`markConversationRead`。
- 純函式 `applyMarkRead`/`countUnread`/`describeNotification` 有單測(含三種 type 文案)。

## Task 6 — NotificationCenter + ChatApp 接線

Goal：鈴鐺 + 未讀紅點 + 下拉列表 + 點擊導航;WS 進來 upsert;開對話標已讀。
Files：`frontend/chat/src/components/NotificationCenter.tsx`、`...NotificationCenter.test.tsx`、`frontend/chat/src/ChatApp.tsx`、`frontend/chat/src/components/Sidebar.tsx`。
Acceptance Criteria：
- 鈴鐺顯示未讀數(>9 → 9+);下拉列每筆顯示 actor + 文案 + 摘要 + 未讀圓點。
- 點一筆 → `selectConversation` + 標已讀(紅點下降);開下拉本身不標已讀。
- `ChatApp` 掛載時載入通知;`case 'notification'` 即時加入;`selectConversation` 呼叫 markRead。
- 元件測試:渲染列表、未讀紅點、點擊呼叫導航 callback。

## Task 7 — E2E + 文件

Goal：Playwright E2E(BDD→Playwright 追溯)與文件更新。
Files：`e2e/tests/notifications-api.spec.ts`、`e2e/tests/notifications-ui.spec.ts`、`e2e/tests/helpers.ts`、`e2e/README.md`、`progress.md`、`acceptance.md` 勾選。
Acceptance Criteria：
- API spec:reply/react/forward → 收件人通知(NB-01..03)、不通知自己(NB-06)、未讀數(NB-05)、離線補齊(NB-14)、權限(NB-10/11/12)。
- UI spec:鈴鐺紅點出現、點通知導向對話並清未讀(沿用 `retryAction` 吸收 dev WS 時序)。
- 每個 BDD scenario 對到至少一個自動化測試;README 追溯表更新。
