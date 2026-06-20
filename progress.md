# 進度紀錄（progress.md）

> 給接手的 session：先讀本檔 → 讀 [CLAUDE.md](CLAUDE.md) → 需要時讀設計文件
> [docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md)。
> 最後更新：2026-06-20

## 一句話現況

MVP + **群組聊天** + **圖片/檔案附件** + **訊息編輯/刪除/表情回應**（皆最小可用）已實作完成、前後端測試全綠。
群組功能在 `feat/group-chat`；附件功能已併入 group-chat；訊息動作在 `feat/message-actions`（從 group-chat 切出）。皆採 subagent-driven 逐 task 完成並 review。

## 訊息編輯/刪除/表情（2026-06-20 完成，feat/message-actions 分支）

- 走 WebSocket：client `edit`/`delete`/`react` → server 廣播統一 `message_updated`（完整訊息）給對話所有在線成員（含操作者）。見 [訊息動作設計](docs/superpowers/specs/2026-06-20-message-actions-design.md)。
- 編輯（限本人、標記 edited_at）、軟刪除（佔位「此訊息已刪除」、遮蔽 content/附件/表情）、表情（固定 6 emoji 白名單、任何成員 toggle、`{emoji,count,user_ids}` 觀看者無關形狀，前端自算「我按過沒」）。
- 後端 pytest 54 passed；前端 chat vitest 28、tsc 乾淨。最終全分支 review：Ready to merge。
- 已修 Minor：編輯/刪除鈕僅在訊息 sent 後顯示（樂觀訊息不顯示）。
- 尚未跑瀏覽器 E2E（自動化測試已涵蓋；本功能 E2E 為選配）。

## 圖片與檔案附件（2026-06-20 完成，feat/file-attachments 分支）

- 兩段式：先 `POST /uploads`（存 `backend/uploads/`、DB 存 Attachment 中繼資料）→ 再走現有 WS 送訊息帶 `attachment_id` 綁定並廣播。下載走授權的 `GET /attachments/{id}`（接受 `?token=` 供 `<img>`）。見 [附件設計](docs/superpowers/specs/2026-06-20-file-attachments-design.md)。
- 功能：一則一附件、圖片內嵌、其他檔案下載連結、單檔 10MB、成員權限。
- 後端 pytest 41 passed（上傳/下載權限/413、WS 帶附件/拒用過或他人附件、遷移）；前端 chat vitest 22 passed、三 app tsc 乾淨。
- E2E：Alice 在群組上傳圖片（內嵌顯示）與 txt（下載連結），皆即時送達。截圖 `attach-01/02`。
- follow-up：非 401 上傳錯誤（如 413 檔案過大）目前無 UI 提示（brief 刻意把上傳 UI 最小化）。

## 群組聊天（2026-06-20 完成，feat/group-chat 分支）

- 統一資料模型：1對1 與群組共用 `Conversation`/`ConversationMember`/`MessageRead`（見 [群組設計](docs/superpowers/specs/2026-06-19-group-chat-design.md)）。
- 功能：建群（命名+選好友）、群組即時收發、成員顯示、每則「已讀 N」、群組未讀數。
- 後端 pytest 29 passed（含 WS 群組廣播、已讀 message_ids、遷移回歸測試）；前端 vitest 21 passed、三 app tsc 乾淨。
- E2E 驗證：Alice 建「專案討論群」(3人)→送訊息→Bob/Cara 讀取→Alice 看到「已讀 2」。截圖 `group-01..02`。
- 修過一個 E2E 才抓到的真 bug：Alembic 0002 在 SQLite 的 `direct_key` 格式與 app 不一致導致遷移後重複建對話（commit `5b79f5c`，已加回歸測試）。

### 群組聊天 follow-up（最終 review 判定可後補，不擋合併）

- **效能**：`message_reads` 缺 `user_id` 索引（`mark_read`/`unread_count` 會 filter user_id，量大會慢）。要補需同步改 model 與新 migration。
- **效能**：`_build_conversation_out` 對每位成員做 N+1 查詢（CLAUDE.md 已聲明 MVP 可接受）。
- **資料完整性（選配）**：未加 `CHECK(type!='direct' OR direct_key IS NOT NULL)`。
- **清潔**：未用 import — `test_models_group.py` 的 `uuid`、`services/conversations.py` 的 `and_`、`alembic/versions/0002` 的 `Sequence`。
- **UX/小**：側欄群組成員數含自己（「· N 人」，與測試一致，刻意）；零好友建群靠後端 400 擋；建群名稱 input 同時有 `aria-label` 與 `<label>`（冗餘）。
- **合併**：分支 `feat/group-chat` 保留中，未併回 `main`（使用者選擇稍後處理）。

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
- ~~尚未 `git init`~~ → 已 `git init`；`main` 有 MVP 初始 commit，群組功能在 `feat/group-chat`（未併回）。
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
