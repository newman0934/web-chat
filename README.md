# chat-web

Web 版即時通訊軟體：1對1 + 群組聊天、附件、訊息編輯/刪除/表情/回覆/轉發、WebRTC 語音視訊、
站內通知、線上狀態。

**技術棧**：前端 React 18 + Vite + **Module Federation**（shell host + auth/chat remotes,
刻意採微前端作為學習目標）;後端 FastAPI + SQLAlchemy 2.0（async）+ WebSocket;
資料庫 SQLite（開發）/ PostgreSQL（正式）;JWT 認證、bcrypt。

設計文件（PRD）：[MVP（1對1）](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md)

各功能規格依 SDD 收於 `docs/superpowers/specs/<feature>/`（`spec.md` / `plan.md`，較新功能另含 `bdd.feature` / `tasks.md` / `acceptance.md`）：
- [群組聊天](docs/superpowers/specs/group-chat/spec.md)
- [圖片與檔案附件](docs/superpowers/specs/file-attachments/spec.md)
- [訊息編輯/刪除/表情](docs/superpowers/specs/message-actions/spec.md)
- [群組管理](docs/superpowers/specs/group-management/spec.md)
- [訊息動作增強](docs/superpowers/specs/message-actions-enhancements/spec.md)
- [語音/視訊通話](docs/superpowers/specs/voice-video/spec.md)
- [回覆/轉發](docs/superpowers/specs/message-reply-forward/spec.md)
- [站內通知](docs/superpowers/specs/in-app-notifications/spec.md)
- [線上狀態](docs/superpowers/specs/presence/spec.md)

## 群組聊天

側欄「＋ 新群組」→ 命名並勾選好友（只能加好友）建立群組。群組支援即時收發、顯示成員數、
每則訊息顯示「已讀 N」（被幾人讀過）。1對1 與群組共用同一套對話/訊息/已讀資料模型。

## 圖片與檔案附件

對話輸入列「📎」可附加單一檔案：圖片在對話內嵌顯示（點擊開新分頁看原圖），其他檔案顯示為
下載連結。單檔上限 10MB。檔案存後端 `backend/uploads/`（git 忽略），下載需為該對話成員。

## 訊息編輯 / 刪除 / 表情回應

對自己的訊息可「編輯」（標記「已編輯」）或「刪除」（軟刪除，顯示「此訊息已刪除」佔位）。
任何對話成員可對訊息按固定快速表情（👍 ❤️ 😂 😮 😢 🙏），泡泡下方顯示各表情計數、再按一次移除。
三種動作皆走 WebSocket，即時同步給對話所有成員。

## 結構

```
chat-web/
├── frontend/
│   ├── shell/   # host (:5000)
│   ├── auth/    # remote: 登入註冊 (:5001)
│   └── chat/    # remote: 對話與訊息 (:5002)
├── backend/     # FastAPI (:8000)
└── docker-compose.yml
```

## 前置需求

- Node 20+（前端）
- Python 3.11+（後端）
- Docker（選用；僅在要用 Postgres 而非預設 SQLite 時需要）

## 啟動後端

本地開發**預設用 SQLite**，免 Docker：

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate          # Windows;macOS/Linux 用 source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL="sqlite+aiosqlite:///$(pwd)/dev.db"    # Windows PowerShell: $env:DATABASE_URL=...
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

要用 Postgres（接近正式環境）時，改 `DATABASE_URL`（見 `.env.example`）或 `docker compose up -d db`。

## 啟動前端

> ⚠️ **Module Federation 關鍵**：remote（auth / chat）**不能用 `npm run dev`** ——
> dev server 不產生 `remoteEntry.js`，host 會 404。remote 必須 `build` 後 `preview`；
> 只有 host（shell）可以跑 dev。**改了 remote 要重新 build。**

```bash
# auth remote（:5001）
cd frontend/auth && npm install && npm run build && npm run preview

# chat remote（:5002）
cd frontend/chat && npm install && npm run build && npm run preview

# shell host（:5000）
cd frontend/shell && npm install && npm run dev
```

開 http://localhost:5000 。

## 測試

```bash
# 後端(檔案型 SQLite,免外部服務)
cd backend && python -m pytest

# 前端(各 app)
cd frontend/<app> && npm run test        # vitest
cd frontend/<app> && npm run typecheck   # tsc --noEmit

# E2E(Playwright,需起整套;webServer 會自動 build+preview)
cd e2e && npx playwright test
```

CI(`.github/workflows/ci.yml`)在 push main / PR 時跑 backend pytest 與前端三 app
typecheck/vitest。

> 微前端的「獨立部署」展示：`npm run build` 各 remote 產生 `remoteEntry.js`，shell 透過 URL 載入。
