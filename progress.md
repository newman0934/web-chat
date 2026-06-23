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
> 最後更新：2026-06-23

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

# 測試狀態

## Backend

- Pytest：PASS

---

## Frontend

- Vitest：PASS
- TypeScript Type Check：PASS

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

目前仍為 MVP 基礎版本。

---

## feat/group-chat

目前最新整合分支。

包含：

- 群組聊天
- 附件
- 訊息動作
- 通話
- 通知

尚未合併回 main。

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

### emoji-mart Bundle 偏大

目前直接打包進 Chat App。

未來可改 Lazy Load。

---

### Conversation 查詢存在 N+1

目前 MVP 規模可接受。

若資料量增加需優化。

---

# 下一步建議

## P1

合併：

```text
feat/group-chat
→ main
```

建立正式 Release。

---

## P2

建立 GitHub Actions。

包含：

- Backend CI
- Frontend CI
- Playwright E2E

---

## P3

加入 TURN Server。

改善 WebRTC 穿透率。

---

## P4

優化查詢效能。

包含：

- Message Reads Index
- Conversation N+1

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
