# 進度紀錄（progress.md）

> 給接手的 session：先讀本檔 → 讀 [CLAUDE.md](CLAUDE.md) → 需要時讀設計文件
> [docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md)。
> 最後更新：2026-06-22

## 一句話現況

MVP + **群組聊天** + **圖片/檔案附件** + **訊息編輯/刪除/表情回應** + **語音/視訊通話（1對1，WebRTC P2P）** + **群組管理（成員/角色/改名）** + **訊息動作小增強（編輯歷史/時限、自由 emoji、還原刪除）** + **回覆/轉發** + **站內通知** （皆最小可用）已實作完成、前後端測試全綠。
全部疊在 `feat/group-chat` 整合分支上（各功能各自切支、review 後 `--no-ff` 併回）；`main` 仍保留在後（使用者選擇稍後處理）。
**E2E**：`e2e/` 為 Playwright 套件（REST+WS 風格最省 token），全套涵蓋 reply/forward、群組管理、訊息動作（API+UI）、通話訊號、站內通知（API+UI）。**Docker/Postgres 路徑已驗**（`docker compose up` 全套容器健康，migration 0009 在 SQLite/Postgres 雙驗）。

## 站內通知（2026-06-22 完成，feat/in-app-notifications 分支，走嚴格 SDD）

- 功能：別人對「你的訊息」reply/reaction/forward 時產生持久化通知；chat remote 鈴鐺 🔔 + 未讀紅點 + 下拉通知中心；**開啟該訊息所在對話即標已讀**（已讀唯一來源）。一事件一通知、不通知自己、reaction toggle 移除不刪。見 [SDD 產物](docs/superpowers/specs/in-app-notifications/)。
- 後端：新表 `Notification`（migration 0009）；`services/notifications.py`（建立/序列化/列表/未讀數/標已讀）；三處 WS handler 在「與觸發訊息同一 transaction」內建立通知、在線推 `{type:notification}`；REST `GET /notifications`（含 unread_count）、`POST /notifications/read {conversation_id}`。
- 前端：contracts 型別 + WS 事件、`notifications.ts` 純函式、store（notifications/unreadCount + 三 action，未讀總數以伺服器為準）、`NotificationCenter`、ChatApp 接線（mount 載入、WS 即時、開對話標已讀）。
- 測試：backend pytest 120 passed（test_notifications 14）；chat vitest 84 passed（notifications 4 + store +3 + NotificationCenter 5）；三 app tsc 乾淨；e2e notifications-api 9 + notifications-ui 1 綠。
- 走嚴格 SDD：spec→bdd→plan→tasks→approval→逐 task TDD+commit→Playwright→review。

## 訊息動作小增強（2026-06-21 完成，feat/message-actions-enhancements 分支）

- 在既有 edit/delete/react 上補三項：**編輯歷史/版本紀錄 + 15 分鐘編輯時限**、**自由 emoji 選擇器（快速 6 + emoji-mart 完整選擇器）**、**寄件人 5 分鐘內還原已刪除訊息**。見 [小增強設計](docs/superpowers/specs/2026-06-21-message-actions-enhancements-design.md)。
- 資料：新表 `MessageEdit`（編輯前快照，migration 0007）；刪除改為**非破壞性**（DB 保留 content、輸出層遮蔽），還原即清 `deleted_at`；`MessageOut` 加 `deleted_at`。
- 端點：WS 新增 `restore`；REST 新增 `GET /messages/{id}/edits`（成員 only 404、已刪 403，回各版本+目前）。表情驗證由固定白名單改為「單一 emoji」形狀（≤8 codepoints、無 ASCII 英數/空白）。
- 時窗（15min 編輯 / 5min 還原）後端強制；前端常數僅控制按鈕顯隱。
- 後端 pytest 88 passed；前端 chat vitest 54 passed、tsc 乾淨、build OK（emoji-mart ~700KB 進 chat 包）。
- 最終全分支 review（opus）：Ready to merge — 內容洩漏面全數遮蔽（含回歸測試，曾於 loop 內抓到並修掉 `_build_conversation_out.last_message` 洩漏）。
- follow-up（不擋合併）：`is_valid_reaction_emoji` 為粗略啟發式（CJK/符號 ≤8cp 也會過）；EditHistoryPopover 用 index key；emoji-mart bundle 偏大可日後 lazy-load。
- E2E：手動（兩帳號：編輯→看歷史→超時不可編輯；刪除→5 分鐘內還原；按白名單外 emoji）。
- **新流程提醒**：CLAUDE.md 已加入嚴格 SDD workflow（BDD + Playwright + `<feature>/` 目錄 + approval gate），**從下一個功能才開始套用**；本功能維持 superpowers brainstorming→plan→subagent 流程跑完（使用者決定）。

## 群組管理（成員/角色/改名）（2026-06-21 完成，feat/message-actions 分支）

- 功能：群組改名、加入成員（從好友快選或 email 加非好友）、移除成員、升/降管理員角色、退出群組。
- 架構：`GroupInfoPanel.tsx`（側拉面板）→ `Thread.tsx`（header ⓘ 鈕，`onShowGroupInfo` prop）→ `ChatApp.tsx`（`showInfo` state + `runGroupOp` helper）。ApiClient 四個方法（`addMember`/`removeMember`/`leaveGroup`/`renameGroup`/`setMemberRole`）。
- WS 通知：每次群組操作後後端廣播 `conversation_updated`（或 `conversation_removed` 給被移除/退出成員），前端 `loadConversations` 補刷清單與成員列；被移除端對話即時消失。
- 不變式（後端守門）：最後一位 admin 無法退出或被降級；移除非成員回 404；只有 admin 可執行管理操作（403）。
- E2E：手動驗證（兩/三帳號；步驟見 task-7-brief.md Step 8）。
- 前端 vitest：46 passed（含 GroupInfoPanel 2）；chat + shell tsc 乾淨。

## 語音/視訊通話（2026-06-21 完成，feat/message-actions 分支）

- 1對1 WebRTC P2P 通話，訊號（offer/answer/ICE/reject/hangup）走現有 WebSocket 中繼，媒體流不經後端。
- 功能：撥號（Thread header 📞 鈕，僅 direct 對話）、來電通知（CallOverlay 覆蓋層）、接聽/拒接/掛斷、靜音 🎙️、關鏡頭 📷、離線即時回 `call_unavailable`。
- 架構：`callMachine.ts`（純 reducer）→ `useCall.ts`（副作用 hook）→ `CallOverlay.tsx`（UI）→ `ChatApp.tsx`（接線）。後端 `_handle_call_signal` 轉送訊號（不落庫）、`are_friends` 守門、`call_unavailable` 偵測離線。
- 前端 vitest：callMachine 6 + CallOverlay 4 + 既有 28 = 38 passed，tsc 乾淨。E2E 為手動（兩瀏覽器，STUN-only，localhost 同機）。
- **限制**：無 TURN server，跨 NAT 的不同網路環境可能無法 P2P 穿透；localhost 同機可正常運作。

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

- ~~**Docker 尚不能跑**：WSL2 未設定~~ → **2026-06-22 已可跑**：Docker 29.5.3、WSL2 設定完成。`docker compose up -d db` 起 Postgres 16（healthcheck 通過），已用本地 venv 對 Postgres 跑 `alembic upgrade head` 至 head `0008`，10 張表全建（**migration 首次在真 Postgres 驗證通過**，含 0005/0007/0008 回填）。**註：開發/測試仍不需要 Docker**（後端預設走 SQLite）。**全套容器亦已驗證**（2026-06-22）：補 `backend/.dockerignore`（排除 `.venv`/`*.db`/快取）後 `docker compose up -d --build` 成功 build `chat-web-backend` image，db+backend 兩容器健康；`/health` OK，且 register→login→`/users/me` 全通、資料確實寫入 Postgres `users` 表。
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
