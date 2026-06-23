# 線上狀態(presence)— Spec

- 日期：2026-06-22
- 狀態：待核可(approval gate)
- 分支：`feat/presence`(疊在 `feat/group-chat` 之上)

## Overview

顯示好友的**線上/離線**狀態與**最後上線時間**。online 與 last_seen 皆由現有 WebSocket 連線層(`ConnectionManager`,**in-memory、單程序**)管理:online = 是否有連線;last_seen = 最後一條連線斷開的時間,記在記憶體。只對**好友**(Contact)廣播與顯示。初始狀態併進現有 `GET /contacts` 回應,即時變化走新的 server→client WS 事件 `presence`。前端在 Sidebar 好友/對話列顯示綠/灰點,1對1 Thread header 顯示「在線」或「最後上線 X」。

> **實作註記(presence 全程不從 WS 生命週期寫 DB)**:原設計擬把 `last_seen_at` 持久化於 `User`。實作時發現 —— 在 starlette `TestClient` 的關閉(teardown join)路徑中,於 WS 端點 disconnect 開 DB session 會死結;且「每次連線就寫 DB」在整體測試下也會誘發 SQLite 死結。因 presence 本就是 in-memory、單程序架構,故 last_seen 一併存記憶體(`ConnectionManager`)。`User.last_seen_at` 欄位與 `0010` 遷移**保留**作為未來耐久化(Redis / 多 worker)的掛勾,執行期不寫。

## Business Requirements

- BR-1：使用者能一眼看出好友目前是否在線。
- BR-2：好友離線時能看到他「最後上線」的相對時間。
- BR-3：狀態即時更新(好友上線/離線時,在線的我立即看到變化)。
- BR-4：隱私邊界 —— 只有好友能看到彼此的 presence;非好友拿不到。
- BR-5：維持微前端邊界(presence 屬 chat 領域,shell 不動)。

## Functional Requirements

- FR-1：online = 該使用者目前至少有一條 WS 連線;offline = 無任何連線。
- FR-2：使用者**第一條**連線上線時 → 對其所有**在線好友**廣播 `{type:'presence', user_id, online:true, last_seen_at:null}`。
- FR-3：使用者**最後一條**連線斷開時 → 在記憶體記下 `last_seen = now()`,對其所有在線好友廣播 `{type:'presence', user_id, online:false, last_seen_at}`。
- FR-4：同一使用者多分頁/裝置:只有首條上線、末條離線才廣播(中間的連線增減不廣播)。
- FR-5：`GET /contacts` 每筆好友帶 `online`(記憶體即時)與 `last_seen_at`(記憶體;從未離線過則 null)。
- FR-6：前端依初始快照 + WS `presence` 事件維護好友狀態,於 Sidebar 與 1對1 Thread header 呈現。

## Acceptance Criteria

- AC-1：Bob(Alice 的好友)建立第一條 WS 連線 → 在線的 Alice 收到 `presence{user_id:Bob, online:true}`。
- AC-2：Bob 最後一條連線斷開 → Alice 收到 `presence{user_id:Bob, online:false, last_seen_at:<≈now>}`,且 manager(記憶體)記下 Bob 的 last_seen。
- AC-3：Bob 已有一條連線,再開第二條 → **不**再廣播 online(避免重複);關掉其中一條(仍有一條)→ **不**廣播 offline。
- AC-4：Alice 呼叫 `GET /contacts` → 每筆好友含 `online`(反映當下連線)與 `last_seen_at`。
- AC-5：非好友 Carol 連線/斷線 → Alice **不**收到 Carol 的 presence;Alice 的 `/contacts` 不含 Carol。
- AC-6：前端 Sidebar 對 1對1 對方顯示綠點(online)/灰點(offline);Thread header 顯示「在線」或「最後上線 X」。

## Edge Cases

- EC-1：上線當下,某好友離線 → 該好友收不到即時事件,但其下次 `GET /contacts` 會取得正確快照。
- EC-2：廣播對象僅「在線的好友」(離線者本就無 WS 可收)。
- EC-3：dev + React.StrictMode 雙連線:同人兩條連線,第二條不重複廣播 online、倒數第二條斷開不誤報 offline(靠 first/last 判斷)。
- EC-4：last_seen_at 為 NULL(從未上線過/剛註冊)→ 前端離線時顯示「離線」而非「最後上線 (空)」。
- EC-5：時鐘/時區 —— last_seen_at 一律 tz-aware UTC 序列化(沿用 `app/timeutils.to_utc_iso`),前端以相對時間呈現。
- EC-6：群組對話不顯示 presence(可見範圍=好友;群組成員狀態本功能不做)。

## API Contracts

### REST(擴充既有)

```
GET /contacts
  200 → ContactOut[]，每筆新增：
        online: bool
        last_seen_at: datetime | null
```

### WebSocket(server → client,新增)

```
{ type:'presence', user_id: uuid, online: bool, last_seen_at: datetime | null }
# 由連線生命週期觸發,廣播給該 user 的在線好友。無新 client→server 類型。
```

## Data Model Changes

`User` 新增欄位(migration `0010`):
```
last_seen_at  DateTime(timezone=True) NULL   # 保留欄位,執行期不寫(見 Overview 實作註記)
```
- online 與 last_seen 皆不落庫(in-memory `ConnectionManager`)。
- 欄位保留供未來耐久化;無回填(預設 NULL)。

## State Changes

### 後端
- `ConnectionManager.connect/disconnect` 回傳 bool:是否為該 user 的第一條/最後一條連線;另以 `mark_last_seen`/`get_last_seen` 在記憶體保存 last_seen。
- WS 端點在 connect 後(若首條)、disconnect 後(若末條)觸發 presence 廣播;末條時先 `mark_last_seen`(記憶體)。連線當下(健康路徑)讀好友清單並快取,斷線只用快取廣播、不碰 DB。
- 新 `app/services/presence.py`:`get_friend_ids`、`build_presence_event`(不寫 DB)。

### 前端(chat remote)
- `store`:`presence: Record<userId, {online: boolean; last_seen_at: string | null}>`;`setPresenceFromContacts(contacts)`、`applyPresence(evt)`。
- `presence.ts` 純函式:`applyPresence(map, evt)`、`formatLastSeen(ts, now?)`。
- ChatApp:`handleServerMessage` 加 `case 'presence'`;載入 contacts 後 `setPresenceFromContacts`。

## UI Behaviour

- **Sidebar**(好友清單 / 1對1 對話列):對方名稱旁一個小圓點 —— 綠(online)/ 灰(offline)。
- **Thread header**(僅 1對1):標題下方小字:online → 「在線」;offline → 「最後上線 {相對時間}」;last_seen_at 為 null 的 offline → 「離線」。
- **相對時間格式**(`formatLastSeen`):< 1 分鐘「剛剛」、< 60 分鐘「N 分鐘前」、< 24 小時「N 小時前」、否則「M/D」。
- 群組 header 不顯示 presence。

## Non-Functional Requirements

- NFR-1(效能):presence 廣播為 O(好友數);`/contacts` 的 online 與 last_seen 皆為記憶體查詢,無額外 N+1。
- NFR-2(安全):presence 僅對好友廣播/顯示;非好友無法取得他人 online/last_seen。
- NFR-3(一致性):末條連線斷開先在記憶體寫 last_seen 再廣播,事件帶到的時間與 manager 內值一致。
- NFR-4(相容):`last_seen` 經 `to_utc_iso` 序列化為 tz-aware UTC,避免時間錯位(見 [[postgres-vs-sqlite-datetime-tz]] 類陷阱)。
- NFR-5(擴充性):in-memory presence(含 last_seen)限單程序、不跨重啟;水平擴充 / 耐久化需 Redis pub/sub 或回填 `User.last_seen_at`(本功能不做,欄位已保留)。
