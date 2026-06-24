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

# 測試狀態

## Backend

- Pytest：PASS（150）

---

## Frontend

- Vitest：PASS（chat 117）
- TypeScript Type Check：PASS（chat / shell / auth）

---

## E2E

- Playwright：PASS

---

## Docker

- Docker Compose：PASS
- Postgres Migration：PASS

---

# 分支狀態

## main

已含全部功能(MVP + 群組 / 附件 / 訊息動作 / 群組管理 / 通話 / 通知 / 線上狀態)
與本輪重構優化。`feat/group-chat` 已合併回 main,兩者目前指向同一 commit。

---

## feat/group-chat

長期整合分支,與 main 同步(同一 commit)。後續開發在此或 main 皆可。

---

# 已知問題

## Medium

React Router v7 Future Flag Warning

影響：

無功能影響。

建議：

```tsx
<BrowserRouter
  future={{
    v7_startTransition: true,
    v7_relativeSplatPath: true
  }}
>
```

---

## Low

### Emoji 驗證規則較寬鬆

目前採啟發式驗證。

未完全符合 Unicode Emoji 規範。

---

> 已解決(2026-06-24):emoji-mart Bundle 偏大 → 已改 React.lazy 動態載入;
> Conversation 查詢 N+1 → 已批次化(serialize_conversations_out);
> 上傳記憶體耗盡風險 → 已改分塊讀取。詳見「重構與優化（2026-06-24）」。

---

# 下一步建議

## P1

✅ `feat/group-chat → main` 已合併(2026-06-24)。

接著可建立正式 Release / 打 tag。

---

## P2

GitHub Actions:✅ workflow 已備(`.github/workflows/ci.yml`,Backend CI + Frontend CI)。
待加 git remote / 推上 GitHub 才會實際執行;Playwright E2E 較重,日後可另開 job。

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
