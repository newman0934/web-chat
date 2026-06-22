# 線上狀態 — 實作計畫(plan)

對應 [spec.md](spec.md) 與 [bdd.feature](bdd.feature)。

## Architecture

online 來自 in-memory `ConnectionManager`(現成);presence 轉換點是「使用者第一條連線上線」「最後一條連線斷開」,於 WS 端點的 connect/disconnect 生命週期觸發。轉換時對該使用者的**在線好友**廣播 `presence` 事件。離線轉換先把 `User.last_seen_at` 寫 DB 再廣播(事件帶到的時間與 DB 一致)。初始狀態不另開端點,直接把 `online`/`last_seen_at` 併進既有 `GET /contacts`。集中邏輯放 `app/services/presence.py`。前端全在 chat remote:store 維護 `presence` map,Sidebar 綠/灰點、1對1 Thread header 文案;shell 不動。

## Backend Changes

- `app/models/user.py`:加 `last_seen_at: Mapped[datetime | None]`。
- `alembic/versions/0010_user_last_seen.py`:User 加 `last_seen_at`(nullable,無回填)。
- `app/ws/manager.py`:`connect` 回傳 `is_first`(該 user 由 0→1 條);`disconnect` 回傳 `is_last`(由 1→0 條)。
- `app/services/presence.py`:
  - `get_friend_ids(db, user_id) -> set[uuid]`(查 Contact)。
  - `set_last_seen(db, user_id) -> datetime`(寫 now() 並回傳)。
  - `build_presence_event(user_id, online, last_seen_at) -> dict`(用 `to_utc_iso`)。
  - `presence_for_contacts(db, contact_ids) -> dict[uuid, datetime|null]`(批次取 last_seen,供 ContactOut)。
- `app/ws/router.py`:connect 後若 `is_first` → 廣播 online 給在線好友;disconnect 後若 `is_last` → `set_last_seen` + 廣播 offline。新 helper `_broadcast_presence(db, user, online, last_seen_at)`(只送 `manager.is_online` 的好友)。
- `app/routers/contacts.py`:`list_contacts` 帶入 `online`(`manager.is_online`)與 `last_seen_at`。
- `app/schemas.py`:`ContactOut` 加 `online: bool = False`、`last_seen_at: datetime | None`(用既有 `_utc_iso` field_serializer)。

## Frontend Changes(chat remote)

- `frontend/contracts/index.ts`:`Contact` 加 `online: boolean`、`last_seen_at: string | null`;`ServerWsMessage` 加 `{type:'presence', user_id, online, last_seen_at}`。
- `frontend/chat/src/presence.ts`(純函式):`applyPresence(map, evt)`、`formatLastSeen(ts, now?)`。
- `frontend/chat/src/store.ts`:`presence` map + `setPresenceFromContacts`、`applyPresence`。
- `frontend/chat/src/ChatApp.tsx`:`handleServerMessage` 加 `case 'presence'`;載入 contacts 後 `setPresenceFromContacts`;把 presence 傳給 Sidebar / Thread。
- `frontend/chat/src/components/Sidebar.tsx`:1對1 對話列對方旁綠/灰點(以 `presence[otherUserId]`)。
- `frontend/chat/src/components/Thread.tsx`:1對1 header 標題下方狀態小字(props 注入,維持可測)。

## Database Changes

- `users` 加 `last_seen_at TIMESTAMP WITH TIME ZONE NULL`(migration 0010)。SQLite/Postgres 皆相容,無回填。

## API Changes

- `GET /contacts` 回應每筆加 `online` / `last_seen_at`。
- WS 新增 server→client `presence`(無新 client→server)。

## State Management Changes

- store 新增 `presence: Record<userId,{online,last_seen_at}>`。
- 來源:`/contacts` 初始快照(`setPresenceFromContacts`)+ WS `presence`(`applyPresence`)。

## File Changes

新增:
- `backend/alembic/versions/0010_user_last_seen.py`
- `backend/app/services/presence.py`
- `backend/tests/test_presence.py`
- `frontend/chat/src/presence.ts`
- `frontend/chat/src/presence.test.ts`
- `e2e/tests/presence-api.spec.ts`(WS + REST)

修改:
- `backend/app/models/user.py`、`app/ws/manager.py`、`app/ws/router.py`、`app/routers/contacts.py`、`app/schemas.py`
- `frontend/contracts/index.ts`、`frontend/chat/src/{store,ChatApp}.ts(x)`、`components/{Sidebar,Thread}.tsx`
- 既有 manager 測試(connect/disconnect 回傳值變更需同步)

## Risks

- R-1:`ConnectionManager.connect/disconnect` 簽章改變(回傳 bool)→ 既有呼叫端與測試需同步;影響面小、集中。
- R-2:in-memory presence 限單程序;水平擴充需 Redis(文件註明,不做)。
- R-3:last_seen_at tz —— 一律 `to_utc_iso`,避免 SQLite naive 錯位(已有前例陷阱)。
- R-4:dev StrictMode 雙連線 → first/last 判斷確保不抖動;E2E 用獨立連線驗首尾。
- R-5:廣播時序(disconnect 後 user 物件可能已脫離 session)→ 廣播只需 user_id 與時間,先取好純量再廣播。

## Implementation Order

依 tasks.md:1 模型+0010 → 2 manager first/last + presence service → 3 WS 廣播 + contacts 帶 presence → 4 contracts+store+純函式 → 5 Sidebar/Thread UI + ChatApp 接線 → 6 E2E + 文件。每 task TDD、可獨立 review。
