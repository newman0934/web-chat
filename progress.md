# Progress

> 接手新 Session：
>
> 1. 先讀 CLAUDE.md
> 2. 再讀本檔
> 3. 需要時再閱讀設計文件
>
> 設計文件：
>
> docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md
>
> 最後更新：2026-06-24

---

# 專案狀態

目前 Chat Web 已完成 MVP 與主要加值功能。

目前系統可正常運作。

所有核心功能已完成並通過測試。

---

# 已完成功能

## MVP

- Email / Password 註冊
- Email / Password 登入
- JWT Authentication
- Email 加好友
- 1 對 1 即時聊天
- WebSocket 即時訊息
- 歷史訊息分頁
- 已讀狀態
- 自動重連

---

## 群組聊天

已完成。

包含：

- 建立群組
- 群組即時聊天
- 群組未讀數
- 成員列表
- 已讀人數顯示

狀態：

PASS

---

## 附件功能

已完成。

包含：

- 圖片上傳
- 檔案上傳
- 圖片預覽
- 檔案下載
- 權限驗證

狀態：

PASS

---

## 訊息功能

已完成。

包含：

- 編輯訊息
- 刪除訊息
- 還原刪除
- 編輯歷史
- Emoji Reaction
- Reply
- Forward

狀態：

PASS

---

## 群組管理

已完成。

包含：

- 改群組名稱
- 新增成員
- 移除成員
- 管理員角色管理
- 退出群組

狀態：

PASS

---

## WebRTC 通話

已完成。

包含：

- 語音通話
- 視訊通話
- 接聽
- 拒接
- 掛斷
- 靜音
- 關閉鏡頭

限制：

目前僅 STUN。

未配置 TURN Server。

跨 NAT 環境不保證成功。

狀態：

PASS

---

## 站內通知

已完成。

包含：

- Reply 通知
- Reaction 通知
- Forward 通知
- 未讀數
- 通知中心
- 自動已讀

狀態：

PASS

---

## 線上狀態（Presence）

已完成（`feat/presence`，疊在 `feat/group-chat` 上）。

包含：

- 好友線上/離線即時廣播（WS `presence` 事件）
- 最後上線時間（離線時顯示「最後上線 X」）
- `GET /contacts` 帶 online / last_seen_at 快照
- Sidebar 1對1 對方綠/灰點、Thread header 狀態文案
- 只對好友廣播/顯示（非好友不外洩）
- 多分頁/裝置：只有首條上線、末條離線才廣播

重要設計：presence 全程 **in-memory、單程序**（online 與 last_seen 都存
`ConnectionManager`，不從 WS 生命週期寫 DB）。原因——在 starlette TestClient 的關閉路徑
中於 WS disconnect 開 DB session 會死結；連線當下頻繁寫 DB 在整體測試下也會誘發 SQLite
死結。`User.last_seen_at` 欄位與 `0010` 遷移保留作未來耐久化（Redis / 多 worker）掛勾。
詳見 [docs/superpowers/specs/presence/spec.md](docs/superpowers/specs/presence/spec.md) 的實作註記。

狀態：

PASS（backend pytest 135、chat vitest 101、三 app tsc 乾淨、presence-api E2E 4 於
SQLite + Postgres 雙環境綠）

---

# 重構與優化（2026-06-24）

線上狀態完成後做了一輪行為保留的整理,皆以既有測試(必要時加 E2E)當安全網、零行為變動。

## 檔案架構重構（5 項）

- `backend/app/ws/router.py`(595→120 行）：拆成 `ws/handlers/{messages,calls}.py`、
  `ws/serializers.py`、`ws/wsutils.py`;router 只留端點 + 分派 + presence 生命週期。
- `frontend/chat/src/components/Thread.tsx`(549→約 250 行）：拆出 `MessageBubble` /
  `ReactionPicker` / `ReplyQuoteBlock` 各自成檔。
- `ChatApp.tsx`：抽出 `wsDispatch.ts`(WS 分派純函式,新增單元測試）與
  `useMessageActions.ts`(訊息動作 hook）。
- `routers/conversations.py`：序列化下放 `services/conversations.py`
  (`serialize_conversation_out` / `serialize_message_out`）。
- WS 與 REST 訊息序列化收斂為單一真相(WS 改用 `MessageOut.model_dump`）。

## 效能 / 安全 / UX 優化（5 項）

- 上傳改**分塊讀取**:先看 Content-Length、累計超過 10MB 即中止,避免整檔載入記憶體
  (記憶體耗盡風險)。
- `list_conversations` 消除 **N+1**:`serialize_conversations_out` 批次化,查詢數固定
  (成員/角色/使用者/最後訊息/已讀/未讀各一次,最後訊息用 window function)。等價性有測試保證。
- 上傳失敗**顯示錯誤訊息**(原本靜默吞掉 413/415);Thread 紅色橫幅。
- `emoji-mart`(~700KB)改 **React.lazy 動態載入**,拆出主 bundle、只在開「更多表情」時抓。
- `message_reads.user_id` **加索引**(+ `0011` 遷移),加速 unread_count / mark_read。

## 其他

- 依全局語言規範,把殘留**英文註解 / docstring 統一為繁中**(保留識別字、API 路徑、套件名等豁免項)。
- `docs/` 依 SDD 架構重整:每功能一資料夾(`specs/<feature>/`),舊 design/plan 併入。

驗證:backend **139 passed**、chat vitest **111 passed**、三 app tsc 乾淨;
受影響處(訊息動作 / presence / conversations 批次)於 SQLite + Postgres 雙環境驗過。

---

# 效能與正式環境整備（2026-06-24 後續）

## 效能(N+1 全面清除)

- `list_messages`:每則訊息原本 ~3-6 個查詢(附件/表情/已讀/回覆/轉發)→ `serialize_messages_out`
  批次,查詢數固定。等價性測試 + SQLite/Postgres 雙驗。
- 前端:收到 WS 訊息原本每則都重抓整份 `/conversations` → 改 store `applyIncomingToConversations`
  就地更新(last_message/未讀/置頂),只有新對話才退回重抓。
- `list_contacts`(逐位 `get_or_create`)與 `list_notifications`(每則 2 個 `db.get`)→ 各批次化。
- 註:`attachment.message_id` 經查證已由 UniqueConstraint 建唯一索引,毋須再加(原誤判)。

## 正式環境整備

- **登入速率限制**:每來源 IP 60 秒內登入失敗 10 次 → 429(只記失敗;記憶體單程序,
  見 `app/ratelimit.py`),降低暴力破解速度。
- **CI**:`.github/workflows/ci.yml`(backend pytest + 前端三 app typecheck/vitest)。
  ⚠️ repo 目前無 git remote,推上 GitHub 後才會實際執行。
- **請求記錄**:HTTP middleware 記 method/path/status/耗時,**刻意不含 query**
  (`?token=` 不進自家 log;見 `app/logging_config.py`)。

驗證:backend **150 passed**、chat vitest **117 passed**、三 app tsc 乾淨。

---

# GitHub 上線 / Docker / 安全強化（2026-06-24 後續）

## 上 GitHub 與 CI 實跑

- 接上 remote `git@github.com:newman0934/web-chat.git`,以 **main 為主**;`feat/group-chat`
  已刪除。每次 push main / PR 觸發 CI(ci.yml,backend pytest + 前端三 app typecheck/vitest),
  皆綠。

## 前端 Docker 化 + Docker build CI

- 三個 micro-frontend(shell/auth/chat)共用 `frontend/Dockerfile`(以 `APP` build arg
  區分),build context 取 `frontend/` 以解析 `../contracts`。remote 必須 build+preview
  (`vite preview` 才產生 `remoteEntry.js`);`VITE_*` 於 build 時內聯。`docker-compose.yml`
  一鍵起全套(db + backend + 三前端)。
- `.github/workflows/docker-build.yml`:path-filtered(只在 Docker/前後端原始碼變更時跑),
  以 **buildx bake + GitHub Actions layer cache**(每 target 各自 scope)建四個映像。
  cache 命中後 Docker build 從數分鐘降至 **~36 秒**。

## 安全強化(正式環境整備 II)

- **JWT 預設密鑰啟動防護**:`config.ensure_secure()` 於 `environment=production` 仍用預設
  `dev-secret-change-me` 時讓 App **啟動失敗**(否則 token 可被偽造、帳號接管);main.py
  啟動時呼叫。`ENVIRONMENT` 預設 development,本機/compose 不受影響。
- **註冊端點限流**:`/auth/register` 加 `register_limiter`(每 IP 每小時 20 次,每次計入),
  擋自動化大量建帳號。
- backend image Python 對齊 CI(3.11→**3.12**);`backend/.dockerignore` 補排除
  `tests/`、`uploads/`。
- **修非 ASCII 檔名下載 500**:`Content-Disposition` 對中文等非 ASCII 檔名會
  `UnicodeEncodeError`(header 僅 latin-1)→ 改 RFC 6266(`filename*=UTF-8''…` + ASCII
  fallback),補中文檔名下載測試。
- **shell `useAuth` 測試補強**(3→8):初始 loading、logout 清空、網路錯誤亦 logout、
  Bearer 呼叫 /users/me、token 變更後舊回應不覆寫(cancelled 競態)。
- **compose healthcheck**:backend 以 stdlib 戳 `/health`、三前端用 busybox wget 戳
  preview 埠(`127.0.0.1`,避開 IPv6 `::1` 拒連);shell `depends_on` 改
  `condition: service_healthy`,等 remote ready 才起。`up -d --wait` 五容器皆 healthy。

## E2E 進 CI(Playwright)

- 新增 `.github/workflows/e2e.yml`:ubuntu runner 建 backend venv、裝三前端與 e2e 相依、
  `playwright install chromium`,起全棧跑 **51 個 E2E**;path-filtered + 獨立 workflow,
  失敗上傳 report/trace。`workflow_dispatch` 可手動觸發。
- 接 CI 時依序踩到並修掉三個環境差異:
  1. `playwright.config.ts` venv python 路徑**寫死 Windows**(`Scripts/python.exe`)→ 改依
     `process.platform` 切換(Linux 用 `bin/python`)。
  2. backend 缺 `aiosqlite`(它在 `[dev]` 相依群,正式走 Postgres+asyncpg)→ workflow 改裝
     `.[dev]`。
  3. **註冊限流誤擋**:E2E 從同一 runner IP 註冊大量帳號,超過每 IP 20 次/小時即 429,
     後半段測試連環失敗 → 將 `register_rate_limit_max/window` 抽到 Settings(預設仍 20),
     e2e 注入 `REGISTER_RATE_LIMIT_MAX=100000` 等同停用。
- 結果:E2E workflow 於 GitHub 綠燈(51 tests / ~1m36s)。

驗證:backend **156 passed**、chat vitest 117、shell vitest 8、三 app tsc 乾淨;
CI、Docker build、E2E 三條 workflow 於 GitHub 皆綠。

---

# 訊息搜尋（message-search,SDD 全流程,2026-06-24）

依嚴格 SDD 完成第一個新功能(spec/bdd/acceptance/plan/tasks → 批准 → Playwright skeleton →
實作 → 驗證)。規格見 `docs/superpowers/specs/message-search/`。

- **後端**:`GET /search/messages?q=&before=&limit=` —— 跨「我為成員的對話」以
  `lower(col) LIKE` 子字串比對(內容 OR 寄件者名)、排除已刪除、權限隔離、萬用字元逸出;
  批次序列化(無 N+1)、附 `conversation` ref 與 `sender_name`。
  分頁採 `(created_at, id)` keyset、游標只帶錨點訊息 id,時間比較用子查詢「欄對欄」
  (避開 SQLite 秒級 server_default 值與 Python datetime bind 的 `.000000` 微秒格式不一致
  造成漏/重 —— 真 bug,已修並補同刻/分組 tie 測試)。
- `list_messages` 加 `around`(視窗載入)/ `after`(向下分頁),與 `before` 互斥(422)、404 守門。
- **前端**:側欄搜尋框(debounce)+ 結果清單(`<mark>` 高亮、向下分頁);點結果 →
  `around` 載入視窗 → Thread 捲動定位、命中泡泡暫時高亮 ~2s。純函式(highlightParts /
  toSearchResultView / nextSearchCursor)抽離可測。
- **測試**:backend `test_search`(14)+ `test_messages_around`(6);chat `search.test`(9);
  e2e `search-api`(11)+ `search-ui`(1,跳轉高亮)。Postgres 另驗分頁不重不漏與命中。

驗證:backend **175 passed**、chat vitest **127**、e2e **63**、三 app tsc 乾淨;
SQLite + Postgres 雙環境搜尋結果一致。

---

# 訊息置頂（message-pin,SDD 全流程,2026-06-24）

規格見 `docs/superpowers/specs/message-pin/`。

- **資料模型**:`messages.pinned_at`(migration 0012 + `(conversation_id, pinned_at)` 索引);
  `MessageOut.pinned`。
- **後端**:WS `pin`/`unpin`(direct 雙方/group 僅 admin、上限 10、冪等)→ 廣播
  `message_pinned`/`message_unpinned`;`GET /conversations/{id}/pins`(非成員 404、批次序列化);
  刪除已釘訊息自動解釘並廣播。`services/pins.py`(can_pin/count_pins/list_pins)。
- **前端**:側欄無關;Thread 頂部釘選列(最新 + 共 N 則 + 展開 + 點擊沿用 around 跳轉高亮 / 取消),
  泡泡動作加「釘選/取消釘選」(依 canPin)+ 📌;WS 事件即時更新。純函式 `pins.ts`
  (canPin/pinnedBarView/addPin/removePin)。
- **測試**:backend `test_pins`(13)+ `test_migration_0012`(1);chat `pins.test`(6);
  e2e `pin-api`(10)+ `pin-ui`(1)。Postgres 另驗 list_pins 排序/count/can_pin。

驗證:backend **190 passed**、chat vitest **133**、e2e **74**、三 app tsc 乾淨;
SQLite + Postgres 雙環境一致。

---

# 測試狀態

## Backend

- Pytest：PASS（190）

---

## Frontend

- Vitest：PASS（chat 133、shell 8）
- TypeScript Type Check：PASS（chat / shell / auth）

---

## E2E

- Playwright：PASS（74 tests,於 GitHub e2e.yml workflow 跑全棧）

---

## Docker

- Docker Compose：PASS（db + backend + 三前端一鍵起;全服務有 healthcheck,
  `up -d --wait` 五容器皆 healthy、shell 等 auth/chat ready 才起）
- Docker Build（CI,buildx bake + GHA cache）：PASS
- Postgres Migration：PASS

---

# 分支狀態

## main（唯一主分支）

已含全部功能(MVP + 群組 / 附件 / 訊息動作 / 群組管理 / 通話 / 通知 / 線上狀態)、
重構優化、Docker 化與安全強化。已接 GitHub remote
`git@github.com:newman0934/web-chat.git`,後續開發以 main 為主。

`feat/group-chat` 已合併並**刪除**。

---

# 已知問題

## Low

### Emoji 驗證規則較寬鬆

目前採啟發式驗證。

未完全符合 Unicode Emoji 規範。

---

> 已解決(2026-06-24):emoji-mart Bundle 偏大 → 已改 React.lazy 動態載入;
> Conversation 查詢 N+1 → 已批次化(serialize_conversations_out);
> 上傳記憶體耗盡風險 → 已改分塊讀取。詳見「重構與優化（2026-06-24）」。
> React Router v7 Future Flag Warning → 已於 `shell/src/main.tsx` 設 `v7_startTransition`
> 與 `v7_relativeSplatPath`,警告消除。

---

# 下一步建議

## P1

✅ `feat/group-chat → main` 已合併並刪除;✅ 已上 GitHub(remote
`git@github.com:newman0934/web-chat.git`,以 main 為主)。

接著可建立正式 Release / 打 tag。

---

## P2

✅ GitHub Actions 已實跑:CI(backend pytest + 前端三 app)、Docker build
(buildx bake + GHA cache)、**E2E**(Playwright 51 tests 全棧,`e2e.yml`)三條
workflow 於 push main / PR 觸發,皆綠。

正式部署前提醒:設 `ENVIRONMENT=production` 並以環境變數覆寫 `JWT_SECRET`
(否則 `ensure_secure()` 會擋下啟動)。

---

## P3

加入 TURN Server。

改善 WebRTC 穿透率。

---

## P4

✅ 查詢效能優化已完成(2026-06-24):Message Reads Index、Conversation N+1。
後續若有需要再針對其他熱點(如群組大量訊息分頁)評估。

---

# 本地啟動

請直接參考：

```text
CLAUDE.md
```

避免重複維護兩份文件。

---

# Demo 帳號

Alice

```text
alice@example.com
secret123
```

Bob

```text
bob@example.com
secret123
```

---

# 備註

本專案已採用：

- Module Federation
- FastAPI
- WebSocket
- WebRTC
- Playwright
- Spec Driven Development (SDD)

所有新功能請遵循 CLAUDE.md 中定義的流程。

不要直接實作需求。

先完成：

Spec
→ Acceptance
→ Plan
→ Tasks
→ Approval

再進入開發階段。
