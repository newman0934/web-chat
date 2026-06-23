# chat-web E2E Tests (Playwright)

Playwright E2E test suite for chat-web, covering the 回覆/轉發 (reply/forward) feature BDD scenarios RF-01..09.

## Prerequisites

1. Backend `.venv` already created (`backend/.venv/Scripts/python.exe` exists).
2. Each frontend app has `node_modules` installed (`cd frontend/<app> && npm install`).
3. Node.js 18+ available.

## Installation

```bash
cd e2e
npm install
npx playwright install chromium
```

## Running Tests

```bash
# Run all E2E tests (starts all servers automatically via webServer config)
npm test

# Run with visible browser
npm run test:headed

# Open interactive UI
npm run test:ui

# View last report
npm run test:report
```

## How the Stack is Brought Up

`playwright.config.ts` uses the `webServer` array to start:

| # | Service | Command | Port | Note |
|---|---------|---------|------|------|
| 1 | Backend (FastAPI) | `alembic upgrade head && uvicorn` | 8000 | Uses throwaway `e2e/e2e.db` |
| 2 | Auth remote | `npm run build && npm run preview` | 5001 | Must build — dev server doesn't emit `remoteEntry.js` |
| 3 | Chat remote | `npm run build && npm run preview` | 5002 | Same reason |
| 4 | Shell host | `npm run dev` | 5000 | Host can run as dev server |

`reuseExistingServer: true` means if you already have servers running, Playwright won't restart them.

## Demo Account / Registration Approach

Tests use **fresh per-run accounts** with timestamped emails (e.g. `alice-reply-1234567890@e2e.test`). This ensures test isolation without needing a DB reset between runs. The `apiRegister` helper handles 409 (already registered) gracefully by falling back to login.

## BDD → Test Traceability

| BDD Scenario | Automated Tests |
|---|---|
| RF-01 回覆引用塊 | `reply.spec.ts` (Playwright UI) + `backend/tests/test_ws.py` (pytest) + `frontend/chat` vitest |
| RF-02 轉發標來源 | `forward.spec.ts` (Playwright UI) + pytest + vitest |
| RF-03 轉發帶附件 | `forward.spec.ts` (Playwright API+WS) + pytest |
| RF-04 跨對話回覆拒 | `reply-forward-api.spec.ts` RF-04 test + pytest |
| RF-05 缺欄位轉發拒 | `reply-forward-api.spec.ts` RF-05 test + pytest |
| RF-06 轉非成員拒 | `reply-forward-api.spec.ts` RF-06 test + pytest |
| RF-07 轉看不到的訊息拒 | `reply-forward-api.spec.ts` RF-07 test + pytest |
| RF-08 轉已刪訊息拒 | `reply-forward-api.spec.ts` RF-08 test + pytest |
| RF-09 引用已刪佔位 | pytest (backend) + vitest (frontend) — no Playwright spec needed (UI-only rendering, covered by component tests) |

### 群組管理（Group Management）

`group-management-api.spec.ts` 走 REST + WebSocket（無 UI），取代原本多帳號手動點擊驗證。

| 場景 | 涵蓋內容 |
|---|---|
| GM-01 admin 加好友入群 | 成員列更新 + 線上成員收到系統訊息與 `conversation_updated` |
| GM-02 用 email 加非好友入群 | 放寬 friends-only，outsider 成功入群 |
| GM-03 移除成員 | 成員列移除該員、被移除者收到 `conversation_removed` |
| GM-04 改名 | name 更新、成員收到 `conversation_updated` + 系統訊息 |
| GM-05 升級成員為 admin | roles 反映、被升級者取得管理權限（可改名） |
| GM-06 成員退出群組 | 回 `{ok:true}`、自己收到 `conversation_removed`、群組少一人 |
| GM-07 非 admin 管理操作 | 改名被拒 403 |
| GM-08 唯一 admin 退出 | 被拒 400 |
| GM-09 移除非成員 | 被拒 404 |
| GM-10 加入已是成員者 | 被拒 400 |

> 這些規則 backend pytest（`test_group_*.py`）已完整覆蓋；Playwright 版本補 E2E 追溯，且 GM-01..06 用持續監聽的 WS 連線實測即時廣播。

### 訊息動作（Message Actions）

`message-actions-api.spec.ts` 純 WebSocket（無 UI）：編輯/刪除/還原/表情。

| 場景 | 涵蓋內容 |
|---|---|
| MA-01 編輯本人訊息 | `message_updated`、content 更新、`edited_at` 非 null |
| MA-02 編輯非本人 | 被拒 forbidden |
| MA-03 編輯空內容 | 被拒 invalid_payload |
| MA-04 刪除本人訊息 | `deleted=true`、content 清空 |
| MA-05 刪除非本人 | 被拒 forbidden |
| MA-06 還原剛刪訊息 | `deleted=false`、content 回來 |
| MA-07 還原未刪訊息 | 被拒 forbidden |
| MA-08 按表情 | reactions 含 `{emoji,count:1,user_ids:[me]}` |
| MA-09 同表情再按 | toggle 移除 |
| MA-10 非成員按表情 | 被拒 forbidden |
| MA-11 編輯廣播 | 線上的另一成員實收 `message_updated` |

> 不自動化 15 分鐘編輯 / 5 分鐘還原時限（需操弄時間，由 backend pytest 以可調時窗覆蓋）。

另有 `message-actions-ui.spec.ts`：真的開瀏覽器、登入、點泡泡上的「編輯/儲存、表情、刪除、還原」鈕，驗畫面對 `message_updated` 廣播的渲染（編輯後內容更新+「已編輯」、👍 chip 高亮、刪除佔位、還原回內容）。

> **dev WS 重試**：chat 的 `send()` 在 socket 未 OPEN 時靜默丟棄、且 edit/delete/react 無失敗重送；dev + React.StrictMode 雙掛載會讓 socket 短暫不穩（production 無此問題）。故 UI spec 對每個動作「重做到 server 反映為止」（`retryAction`），貼近真實使用者「沒反應就再點」，避免假性 flaky。

### 語音/視訊訊號中繼（Call Signaling）

`call-signaling-api.spec.ts` 純 WebSocket，只驗訊號路由與守門（媒體流 P2P 不經後端，不涉真 WebRTC）。

| 場景 | 涵蓋內容 |
|---|---|
| VC-01 call_offer 轉送 | 對端收到、`from.id` 為撥號者、帶 sdp |
| VC-02 call_answer 轉送 | 對端收到、帶 sdp |
| VC-03 call_ice 轉送 | 對端收到、帶 candidate |
| VC-04 reject / hangup 轉送 | 對端皆收到 |
| VC-05 非好友撥號 | 被拒 forbidden |
| VC-06 缺 to_user_id | 被拒 invalid_payload |
| VC-07 對端離線 call_offer | 撥號者收到 `call_unavailable` |

### 站內通知(Notifications）

`notifications-api.spec.ts`(REST+WS)與 `notifications-ui.spec.ts`(瀏覽器 UI)。

| 場景 | 涵蓋內容 |
|---|---|
| NB-01 被回覆 | 收件人得 reply 通知 + 在線收到 WS `notification` |
| NB-02 被按表情 | reaction 通知 + emoji |
| NB-03 被轉發 | forward 通知,conversation 為原訊息所在對話 |
| NB-05 未讀數/列表 | unread_count > 0、列表新→舊 |
| NB-06 自己互動 | 不產生通知 |
| NB-10/11/12 權限 | 只回自己的、401、標非自己對話 marked 0 |
| NB-14 離線補齊 | 離線期間的通知上線後 `GET` 補得回 |
| NUI 鈴鐺 UI | 紅點未讀 → 展開通知中心 → 點通知導向對話並清未讀 |

### 線上狀態(Presence）

`presence-api.spec.ts`(REST+WS,無 UI)。presence 為 in-memory、單程序;last_seen 存
`ConnectionManager`(不落 DB),故 SQLite 與 Postgres 行為一致(雙環境皆驗綠)。

| 場景 | 涵蓋內容 |
|---|---|
| PR-01 上線廣播 | 好友首條連線上線 → 在線的我收到 `presence{online:true}` |
| PR-02 離線廣播 | 好友末條連線斷開 → 我收到 `presence{online:false, last_seen_at}` |
| PR-03/08 contacts 快照 | `GET /contacts` 帶 online/last_seen_at;從未上線好友 false/null |
| PR-04 不重播 | 同一好友第二條連線不再廣播 online |
| PR-05 不誤報 | 倒數第二條連線斷開不誤報 offline;末條才 offline |
| PR-06 隱私 | 非好友上線不廣播給我 |

> 前端呈現(Sidebar 綠/灰點、Thread header「在線/最後上線 X/離線」)由 chat vitest 元件測試覆蓋
> (`presence.test.ts`、`store.test.ts`、`Sidebar.test.tsx`、`Thread.test.tsx`)。
> backend `test_presence.py` 完整覆蓋 manager 首尾、廣播、權限與 /contacts。

## Environment Notes

- **Module Federation constraint**: auth/chat remotes MUST be `build` + `preview`, NOT `vite dev`. The dev server doesn't produce `remoteEntry.js`, causing 404 in the host.
- **RF-04..08 tests** only need the backend (port 8000). They use WebSocket via `page.evaluate` on `about:blank`, so even if the frontend servers fail, these tests can still run.
- **RF-01/02/03 UI tests** need the full stack (all 4 servers).
