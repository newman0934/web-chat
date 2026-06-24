# CLAUDE.md

本文件提供 Claude Code 在此專案中的工作規範。

此工作流程會覆蓋預設的 Superpowers Workflow。

---

# 專案概述

本專案為 Web 版 1 對 1 即時通訊 MVP。

前端刻意採用 Module Federation（微前端）作為學習目標。

後端使用 FastAPI。

主要設計文件（PRD）：

```text
docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md
```

開始任何工作前必須：

1. 閱讀設計文件
2. 閱讀 progress.md
3. 確認目前專案進度與狀態

progress.md 為以下資訊的唯一來源：

- 目前進度
- 剩餘工作
- 已知問題
- 啟動與測試方式

---

# 功能範圍

## 已完成功能

### MVP

- Email / Password 註冊
- Email / Password 登入
- JWT 驗證
- 使用 Email 加好友
- 1 對 1 即時聊天
- WebSocket 即時訊息
- 歷史訊息分頁
- 已讀狀態
- 自動重連

### 群組聊天

- 建立群組
- 群組即時聊天
- 群組未讀數
- 成員列表
- 已讀人數顯示

### 附件功能

- 圖片上傳
- 檔案上傳
- 圖片預覽
- 檔案下載
- 權限驗證

### 訊息功能

- 編輯訊息
- 刪除訊息
- 還原刪除
- 編輯歷史
- Emoji Reaction
- Reply
- Forward

### 群組管理

- 群組改名
- 新增成員
- 移除成員
- 管理員角色管理
- 退出群組

### WebRTC 通話

- 語音通話
- 視訊通話
- 接聽
- 拒接
- 掛斷
- 靜音
- 關閉鏡頭

### 站內通知

- Reply 通知
- Reaction 通知
- Forward 通知
- 未讀通知數
- 通知中心
- 自動已讀

### 訊息搜尋

- 全域搜尋（跨我參與的所有對話）
- 內容 / 寄件者名稱比對（LIKE 子字串、排除已刪除、權限隔離）
- 點結果跳轉並高亮命中訊息

### 訊息置頂

- 釘選 / 取消釘選（WS 即時廣播）
- 群組僅管理員、1對1 雙方可；每對話上限 10 則
- 頂部釘選列、點擊跳轉並高亮
- 刪除已釘訊息自動解釘

### 訊息撤回

- 寄件人 2 分鐘內可撤回（不可復原），與刪除/還原並存
- 清空內容、移除附件與表情、自動解釘
- 撤回後顯示系統訊息「XXX 撤回了一則訊息」
- 已撤回訊息不可再編輯/刪除/表情/釘選/轉發，且不納入搜尋

---

## 已知限制

### WebRTC

目前僅使用 STUN Server。

未配置 TURN Server。

不同 NAT 或企業網路環境可能無法成功建立 P2P 連線。

### 附件功能

目前限制：

- 一則訊息一個附件
- 單檔最大 10MB

### Emoji

目前 Emoji 驗證採簡化規則。

尚未完全遵循 Unicode Emoji 標準。

---

## 未來可能功能

以下功能尚未實作：

- OAuth 登入
- Push Notification
- 多裝置同步通知
- TURN Server
- 群組語音通話
- 群組視訊通話
- 使用者封鎖

---

# 開發指令

## Backend

一律使用 Virtual Environment。

禁止使用系統 Python。

執行所有測試：

```bash
backend/.venv/Scripts/python.exe -m pytest
```

執行單一測試：

```bash
backend/.venv/Scripts/python.exe -m pytest tests/test_ws.py
```

啟動 API：

```bash
cd backend

export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/dev.db"

.venv/Scripts/python.exe -m alembic upgrade head

.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

本地開發預設使用 SQLite。

Docker 與 Postgres 僅於需要時使用。

---

## Frontend

每個前端應用皆獨立管理。

```text
frontend/auth
frontend/chat
frontend/shell
```

各自執行：

```bash
npm install
npm run test
npm run typecheck
```

---

# Module Federation 啟動規則

重要：

Remote App 不可使用 vite dev 提供。

正確啟動方式：

```bash
frontend/auth

npm run build
npm run preview
```

```bash
frontend/chat

npm run build
npm run preview
```

```bash
frontend/shell

npm run dev
```

Port：

```text
5000 shell
5001 auth
5002 chat
```

修改 Remote 後必須重新 Build。

---

# 架構規則

## Frontend

### shell

負責：

- JWT 管理
- 登入狀態管理
- Router 控制

### auth

負責：

- 登入
- 註冊

透過 callback 回傳 token。

### chat

負責：

- 聊天功能
- 訊息畫面

透過 props 接收：

- token
- currentUser

---

### 契約管理

所有跨應用契約集中於：

```text
frontend/contracts/index.ts
```

修改任一邊界時，必須優先更新此檔案。

---

## Backend

### Conversation 規則

Conversation 永遠以：

```text
user_a_id < user_b_id
```

方式儲存。

必須透過：

```python
order_pair()
get_or_create_conversation()
```

建立對話。

禁止繞過此規則。

---

## WebSocket

Client → Server：

- message
- read
- typing

Server → Client：

- ack
- message
- read
- error

訊息流程：

```text
驗證身份
→ 寫入資料庫
→ ACK 發送者
→ 推播接收者
```

---

## Database 規則

UUID 一律使用：

```python
sqlalchemy.Uuid
```

禁止使用：

```python
postgresql.UUID
```

---

### 密碼規則

一律使用：

```python
bcrypt
```

禁止改回：

```python
passlib
```

---

# 測試規則

Backend 測試環境固定使用：

```text
SQLite 檔案資料庫
NullPool
```

禁止改為：

```text
In-Memory SQLite
StaticPool
```

否則 WebSocket 測試會失敗。

---

前端業務邏輯應盡可能抽離 React Component。

可獨立測試的邏輯應以純函式實作。

---
