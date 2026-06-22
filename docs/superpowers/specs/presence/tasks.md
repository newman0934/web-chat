# 線上狀態 — Tasks

每個 task 小、可獨立 review、可獨立測。對應 [plan.md](plan.md)、[bdd.feature](bdd.feature)。

## Task 1 — User.last_seen_at + 0010 遷移

Goal：User 加 `last_seen_at` 欄位與遷移。
Files：`backend/app/models/user.py`、`backend/alembic/versions/0010_user_last_seen.py`、`backend/tests/test_presence.py`。
Acceptance Criteria：
- `User.last_seen_at` 為 `DateTime(timezone=True)` nullable。
- 0010 在 SQLite 與 Postgres 皆 `upgrade head` 成功(新增欄位、無回填)。
- 既有測試不受影響(欄位預設 NULL)。

## Task 2 — ConnectionManager first/last + presence service

Goal：connect/disconnect 回傳首尾旗標;presence 純後端邏輯。
Files：`app/ws/manager.py`、`app/services/presence.py`、既有 manager 測試、`tests/test_presence.py`。
Acceptance Criteria：
- `connect` 回傳 `is_first`(0→1)、`disconnect` 回傳 `is_last`(1→0);多連線只在首尾為 True。
- `get_friend_ids` / `set_last_seen`(寫並回傳 now)/ `build_presence_event`(tz-aware ISO)/ `presence_for_contacts`。
- 單元測試覆蓋首尾判斷、set_last_seen 寫入、好友查詢。

## Task 3 — WS 廣播 + contacts 帶 presence

Goal：連線生命週期廣播 presence;`/contacts` 帶 online/last_seen。
Files：`app/ws/router.py`、`app/routers/contacts.py`、`app/schemas.py`、`tests/test_presence.py`。
Acceptance Criteria：
- 首條上線 → 廣播 online 給在線好友(PR-01);末條離線 → set_last_seen + 廣播 offline(PR-02)。
- 多連線:第二條不重播 online(PR-04)、倒數第二條斷不誤報 offline(PR-05)。
- 非好友上下線不廣播給我(PR-06);廣播只送在線好友(PR-09)。
- `GET /contacts` 每筆含 `online`/`last_seen_at`(PR-03/08);不含非好友(PR-07)。

## Task 4 — contracts + store + 純函式

Goal：型別、WS 事件、store、純邏輯。
Files：`frontend/contracts/index.ts`、`frontend/chat/src/{presence,store}.ts`、`frontend/chat/src/{presence,store}.test.ts`。
Acceptance Criteria：
- `Contact` 加 `online`/`last_seen_at`;`ServerWsMessage` 加 `presence`。
- `applyPresence(map, evt)`、`formatLastSeen`(剛剛/N 分鐘前/N 小時前/日期)有單測。
- store:`presence` map + `setPresenceFromContacts`/`applyPresence`。

## Task 5 — Sidebar/Thread UI + ChatApp 接線

Goal：綠/灰點與 header 文案;接 WS 與初始快照。
Files：`frontend/chat/src/components/{Sidebar,Thread}.tsx`、對應測試、`frontend/chat/src/ChatApp.tsx`。
Acceptance Criteria：
- Sidebar 1對1 對方旁綠(online)/灰(offline)點(PR-10)。
- 1對1 Thread header:online→「在線」、offline→「最後上線 X」、last_seen null→「離線」(PR-11)。
- ChatApp:`case 'presence'` → store.applyPresence;載入 contacts 後 setPresenceFromContacts。
- 群組 header 不顯示 presence。

## Task 6 — E2E + 文件

Goal：Playwright E2E(BDD→Playwright 追溯)與文件更新。
Files：`e2e/tests/presence-api.spec.ts`、`e2e/README.md`、`progress.md`、`acceptance.md` 勾選。
Acceptance Criteria：
- E2E:Bob 上線 → Alice 收 presence online(PR-01);Bob 斷線 → Alice 收 offline + last_seen(PR-02);多連線首尾(PR-04/05);非好友不外洩(PR-06);`/contacts` 帶 presence(PR-03)。
- 每個 BDD scenario 對到至少一個自動化測試;README 追溯表更新。
- 於 SQLite venv 與 Postgres 容器雙環境驗證綠。
