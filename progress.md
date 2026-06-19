# 進度紀錄（progress.md）

> 給接手的 session：先讀本檔 → 讀 [CLAUDE.md](CLAUDE.md) → 需要時讀設計文件
> [docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md)。
> 最後更新：2026-06-19

## 一句話現況

MVP 全部功能已實作完成、前後端測試全綠、瀏覽器端到端 demo 跑過一次成功。可進入打磨 / 部署 / 加值階段。

## 已完成 ✅

- **後端（FastAPI）**：auth（註冊/登入/JWT）、users/me、contacts（email 加好友）、conversations（清單含未讀數+最後訊息、歷史分頁）、WebSocket `/ws`（即時收發、ack 樂觀對齊、已讀回執、斷線資訊）。
- **前端微前端（Module Federation）**：shell host(:5000) + auth remote(:5001) + chat remote(:5002)，契約集中在 `frontend/contracts`。樂觀更新、斷線指數退避重連。
- **測試**：後端 pytest 18 passed；前端 vitest shell 3 / auth 4 / chat 10，全綠。三個前端 app `tsc --noEmit` 乾淨。
- **全程式碼已加上繁中註解**（模組/函式 docstring + 非顯而易見邏輯）。
- **環境**：Python 3.12.10（user-scope）+ backend venv 已建；Node 22。
- **demo 截圖**：專案根目錄 `01-login.png` ~ `06-alice-read-receipt.png`。

## 待辦 / 未完成 ⏳

- **Docker 尚不能跑**：Docker Desktop 已裝，但 WSL2 未設定。需使用者以管理員執行 `wsl --install --no-distribution` → 重開機 → 啟動 Docker Desktop。**註：開發/測試不需要 Docker**（後端走 SQLite）。
- **React Router 未消的 v7 future-flag 警告**（無害）：若要清，於 shell `BrowserRouter` 加 `future={{ v7_startTransition: true, v7_relativeSplatPath: true }}`。
- 尚未 `git init` / 尚未建立任何 commit。
- 尚未產 `/run-skill-generator`（把「shell 跑 dev、remote 要 build+preview」存成啟動技能）。

## 怎麼把整套跑起來（已驗證可行）

```bash
# 後端（SQLite，免 Docker）
cd backend
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/dev.db"
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000

# 前端：remote 必須 build+preview，host 才能跑 dev（關鍵陷阱見 CLAUDE.md）
cd frontend/auth && npm run build && npm run preview   # :5001
cd frontend/chat && npm run build && npm run preview    # :5002
cd frontend/shell && npm run dev                        # :5000
```

開 http://localhost:5000 。demo 帳號：`alice@example.com` / `bob@example.com`，密碼皆 `secret123`。

## 背景服務狀態（本 session 啟動的，可能已隨關機停止）

本 session 曾在背景跑：backend:8000、shell:5000(dev)、auth:5001(preview)、chat:5002(preview)。
新 session 無法沿用舊的背景行程，需要時依上面指令重啟。

## 接手建議的下一步（擇一）

1. `git init` + 首次 commit，把成果版控起來。
2. 清掉 React Router 警告（小事）。
3. 設定 Docker / WSL2 後改用 Postgres 跑 `docker compose up`。
4. 開始加值功能（注意設計文件「明確不做」清單：群組、檔案、語音視訊、推播、OAuth）。
