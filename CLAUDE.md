# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

Web 版 1對1 即時通訊軟體 MVP。**前端刻意採微前端（Module Federation）作為學習目標**，後端 FastAPI。
設計文件（等同 PRD）在 [docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md) — 本專案沒有 `docs/prd/`，實作以該 spec 為準。

**接手前先讀 [progress.md](progress.md)** — 那裡有目前進度、待辦、如何把整套跑起來與 demo 帳號；做完一段工作記得回頭更新它。

驗收範圍：Email+密碼註冊/登入（JWT）、用 email 加好友、1對1 即時文字收發（WebSocket）、歷史訊息分頁、已讀狀態、斷線自動重連。明確不做：群組、檔案/圖片、語音視訊、推播、OAuth。

## 開發指令

### 後端（`backend/`）

Python 用 user-scope 安裝（PATH 上的 `python` 是 Microsoft Store stub，不可用），固定走 venv：

```bash
# venv 已建在 backend/.venv；重建用：
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m venv .venv

backend/.venv/Scripts/python.exe -m pip install -e ".[dev]"   # 安裝
backend/.venv/Scripts/python.exe -m pytest                     # 全部測試
backend/.venv/Scripts/python.exe -m pytest tests/test_ws.py    # 單一檔
backend/.venv/Scripts/python.exe -m pytest tests/test_ws.py::test_ws_message_ack_and_push_and_persist  # 單一測試
```

測試走 SQLite（aiosqlite），**不需要 Postgres / Docker**。

本機跑 API（用 SQLite，免 Docker）：

```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/dev.db"
.venv/Scripts/python.exe -m alembic upgrade head          # 建表
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

正式用 Postgres 時改 `DATABASE_URL`（見 `.env.example`），或 `docker compose up -d db`。

### 前端（`frontend/shell`、`frontend/auth`、`frontend/chat`）

三個 app 各自獨立，每個都要分別 `npm install`。每個 app 都有 `dev` / `build` / `preview` / `test`（vitest）/ `typecheck`（tsc）。

```bash
cd frontend/<app> && npm install
npm run test       # vitest run
npm run typecheck  # tsc --noEmit
```

**啟動整套畫面有一個關鍵陷阱（Module Federation）**：
`@originjs/vite-plugin-federation` 的 remote **不能用 `vite dev` 提供** —— dev server 不產生 `remoteEntry.js`（host 抓會 404）。正確啟動方式：

```bash
# remote 必須 build 後 preview：
cd frontend/auth && npm run build && npm run preview   # :5001
cd frontend/chat && npm run build && npm run preview   # :5002
# 只有 host 可以跑 dev：
cd frontend/shell && npm run dev                       # :5000
```

開 http://localhost:5000 。改動 remote 後要重新 build 才會反映到 host。

## 架構重點（需要跨檔閱讀才懂的部分）

### 微前端邊界

- **shell（host, :5000）**：保管 JWT 與登入狀態（`shell/src/useAuth.ts`），用 react-router 控制 `/login`（掛 auth remote）與 `/`（掛 chat remote）。透過 MF `lazy(() => import('auth/AuthApp'))` 動態載入。
- **auth（remote, :5001）**：暴露 `./AuthApp`，只透過 `onAuthSuccess(token)` callback 把 token 交回 shell。
- **chat（remote, :5002）**：暴露 `./ChatApp`，接收 `token`/`currentUser`/`onLogout`/`apiBaseUrl`/`wsBaseUrl` props。
- **契約集中在 [frontend/contracts/index.ts](frontend/contracts/index.ts)**：shell↔remote 的 props 介面、REST/WS 資料型別、WS 訊息協定都在此。改任一端的邊界都要同步這裡。remote 的型別宣告在 `shell/src/remotes.d.ts`，**必須用 inline `import(...)` 語法**（不可用頂層 import，否則 `declare module` 會變成失效的模組擴充）。
- 共享依賴：`react`/`react-dom`(/`react-router-dom` 僅 shell) 設 shared singleton，避免 hook 衝突。

### 後端

- **對話排序規範**：`Conversation` 永遠以 `user_a_id < user_b_id`（字串比較）儲存，避免同一對人產生兩筆對話。邏輯集中在 `app/services/conversations.py` 的 `order_pair` / `get_or_create_conversation`，REST 與 WS 都共用。
- **WebSocket（`app/ws/`）**：`ConnectionManager` 維護 `user_id → set[WebSocket]`（同人可多連線）。`/ws?token=` 用 query 帶 JWT 驗證，失敗以 code 1008 關閉。Client→Server 類型 `message`/`read`/`typing`；Server→Client 類型 `ack`（帶 temp_id 對齊樂觀訊息）/`message`/`read`/`error`。送訊息流程：驗 sender 屬於該對話 → 寫 DB → 回 ACK 給寄件人 → 收件人在線才推播。
- **WS 端點刻意不走 `get_db` 依賴**，而是直接用 `app.db.SessionLocal`（透過 `from app import db as db_module` + `db_module.SessionLocal()` 延遲引用）。這是為了讓測試能 monkeypatch session factory。改 WS 的 DB 存取時務必保留這個間接層。
- **密碼 hash 直接用 `bcrypt` 套件，刻意不用 passlib**（passlib 1.7.4 與 bcrypt 4.x 不相容）。見 `app/auth/security.py`，hash 前先 `encode()[:72]` 截斷。勿改回 passlib。
- **UUID 主鍵用 SQLAlchemy 2.0 通用 `Uuid` 型別**（非 `postgresql.UUID`），才能在 Postgres 與測試用 SQLite 之間共用。

### 測試策略（非顯而易見處）

- 後端測試（`backend/tests/conftest.py`）用**檔案型 SQLite + `NullPool`**，不是 in-memory。原因：WS 測試用同步的 starlette `TestClient`（自己的 event loop），與 async httpx client（pytest-asyncio loop）需共享資料；NullPool 讓每個 session 在自己的 loop 取得新連線。改測試基礎建設時別退回 in-memory + StaticPool，會踩跨-loop 錯誤。
- 前端純邏輯（樂觀更新）抽成 `chat/src/messageStore.ts` 的純函式，單獨測試，與 React 元件解耦。

## 注意事項

- 全域開發規則在 `~/.claude/CLAUDE.md`（寫碼前讀 PRD、`/dev-flow` 流程等），疊加在本檔之上。
- `vite preview` 的 remote 改動不會 hot-reload，需重新 `build`。
