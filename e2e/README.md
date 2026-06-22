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

## Environment Notes

- **Module Federation constraint**: auth/chat remotes MUST be `build` + `preview`, NOT `vite dev`. The dev server doesn't produce `remoteEntry.js`, causing 404 in the host.
- **RF-04..08 tests** only need the backend (port 8000). They use WebSocket via `page.evaluate` on `about:blank`, so even if the frontend servers fail, these tests can still run.
- **RF-01/02/03 UI tests** need the full stack (all 4 servers).
