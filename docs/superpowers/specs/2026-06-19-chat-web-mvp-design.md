# 通訊軟體 WEB 版 — v1 設計文件

- 日期：2026-06-19
- 狀態：設計定案，待 review
- 範圍：1對1 即時聊天 MVP

## 1. 目標與範圍

打造一個 web 版即時通訊軟體的 v1，核心為「**使用者加好友後進行 1對1 即時文字聊天**」。
前端刻意採用微前端（Module Federation）架構作為學習目標，後端用 Python (FastAPI)。

### v1 驗收範圍

- ✅ Email + 密碼 註冊 / 登入（JWT）
- ✅ 用 email 加好友
- ✅ 1對1 即時文字收發（WebSocket）
- ✅ 歷史訊息（分頁載入）
- ✅ 已讀狀態
- ✅ WebSocket 斷線自動重連

### 明確不做（之後擴充）

- ✅ ~~群組 / 頻道~~ —— 已於 2026-06-20 實作（最小可用），見
  [群組聊天設計](2026-06-19-group-chat-design.md)。
- ✅ ~~圖片 / 檔案傳輸~~ —— 已於 2026-06-20 實作（最小可用），見
  [檔案附件設計](2026-06-20-file-attachments-design.md)。
- ✅ ~~訊息編輯 / 刪除 / 表情回應~~ —— 已於 2026-06-20 實作（最小可用），見
  [訊息動作設計](2026-06-20-message-actions-design.md)。
- ✅ ~~語音 / 視訊~~ —— 已於 2026-06-21 實作（最小可用），見 [語音/視訊設計](2026-06-21-voice-video-design.md)。
- ❌ 推播通知
- ❌ OAuth 第三方登入

## 2. 技術棧

| 層 | 技術 |
|---|---|
| 前端框架 | React 18 + Vite + Tailwind CSS |
| 微前端 | `@originjs/vite-plugin-federation`（Module Federation） |
| 路由 | react-router-dom |
| 後端 | FastAPI（async） |
| ORM / 遷移 | SQLAlchemy 2.0 (async) + Alembic |
| 即時通訊 | FastAPI 原生 WebSocket |
| 認證 | JWT（`python-jose`）+ 密碼 hash（`passlib[bcrypt]`） |
| 資料庫 | PostgreSQL（本地用 Docker Compose） |
| 後端測試 | pytest + FastAPI TestClient |
| 前端測試 | Vitest + Testing Library |

## 3. 整體架構

```
┌─────────────────────────────────────────────┐
│  瀏覽器                                        │
│  ┌──────────── shell (host, :5000) ────────┐ │
│  │  路由 / 版面 / 全域 auth 狀態             │ │
│  │   ├─ 動態載入 ▶ auth remote  (:5001)     │ │
│  │   └─ 動態載入 ▶ chat remote  (:5002)     │ │
│  └──────────────────────────────────────────┘│
└───────────────┬──────────────────┬────────────┘
        REST (登入/歷史)      WebSocket (即時訊息)
                │                  │
        ┌───────▼──────────────────▼────────┐
        │   FastAPI 後端 (:8000)             │
        │   /auth /users /contacts          │
        │   /conversations /messages        │
        │   /ws  (ConnectionManager)        │
        └───────────────┬───────────────────┘
                        │ SQLAlchemy (async)
                  ┌─────▼─────┐
                  │ PostgreSQL │
                  └───────────┘
```

### 倉庫結構（monorepo）

```
chat-web/
├── frontend/
│   ├── shell/      # host app
│   ├── auth/       # remote: 登入註冊
│   └── chat/       # remote: 對話與訊息
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── models/
│   │   ├── routers/
│   │   ├── auth/
│   │   ├── ws/
│   │   └── db.py
│   ├── alembic/
│   └── tests/
├── docker-compose.yml
└── docs/
```

## 4. 微前端拆分與通訊

| App | 角色 | 職責 | 對外介面 |
|---|---|---|---|
| `shell` | Host | 路由、整體版面、保管 JWT 與登入狀態、未登入導向 auth、已登入掛載 chat | 透過 MF 動態 import 兩個 remote |
| `auth` | Remote | 登入/註冊表單，呼叫 `/auth/*`，成功後把 token 交回 shell | `exposes: ./AuthApp`，接收 `onAuthSuccess(token)` callback |
| `chat` | Remote | 對話清單、訊息串、輸入框、開 WebSocket | `exposes: ./ChatApp`，接收 `token` / `currentUser` props |

### App 間通訊

- **shell → remote**：用 props 傳遞 `token`、`currentUser`、callback。remote 不直接碰 shell 內部狀態。
- **remote → shell**：用 callback props（`onAuthSuccess(token)`、`onLogout()`）。
- **共享依賴**：`react`、`react-dom`、`react-router-dom` 設為 `shared singleton`，由 host 提供單一實例，避免 hook 衝突。
- **契約**：remote 對外 props 介面寫成共享 `.d.ts` 契約檔，使邊界清楚、可獨立測試。

### 獨立開發 / 部署

- 每個 app 各自 `package.json`、dev server、build。
- auth / chat 可單獨 build 出 `remoteEntry.js`，shell 透過 URL 載入——展示微前端「獨立部署」核心價值。

> 取捨：單一聊天功能其實不需要拆三個 app，但這是指定的學習目的，因此刻意保留真實 host/remote/shared 邊界，而非形式上假拆。

## 5. 資料模型（SQLAlchemy）

```
User
  id (PK, UUID)
  email (unique)
  display_name
  password_hash
  created_at

Contact                       # 好友關係（雙向，加好友後才能聊天）
  id (PK)
  user_id (FK→User)
  contact_user_id (FK→User)
  created_at
  UNIQUE(user_id, contact_user_id)

Conversation                  # 兩人之間的對話，1對1
  id (PK)
  user_a_id (FK→User)
  user_b_id (FK→User)         # 規範 a<b 排序，避免重複
  created_at
  UNIQUE(user_a_id, user_b_id)

Message
  id (PK)
  conversation_id (FK→Conversation)
  sender_id (FK→User)
  content (text)
  created_at
  read_at (nullable)          # 已讀狀態
```

## 6. REST API

| Method | 路徑 | 用途 |
|---|---|---|
| POST | `/auth/register` | 註冊（email、display_name、password） |
| POST | `/auth/login` | 登入，回傳 JWT |
| GET | `/users/me` | 取得目前使用者 |
| GET | `/contacts` | 好友清單 |
| POST | `/contacts` | 用 email 加好友 |
| GET | `/conversations` | 對話清單（含最後一則訊息、未讀數） |
| GET | `/conversations/{id}/messages?before=&limit=` | 歷史訊息（分頁） |

## 7. WebSocket：`/ws`

- 連線時用 query 帶 JWT 驗證；失敗即關閉連線。
- 後端 `ConnectionManager` 維護 `user_id → WebSocket` 對應（線上者）。
- Client 訊息類型：
  - `{type:"message", conversation_id, content, temp_id}`
  - `{type:"read", conversation_id}`
  - `{type:"typing", conversation_id}`（選配）
- Server 訊息類型：
  - `{type:"ack", temp_id, message}`
  - `{type:"message", message}`
  - `{type:"error", reason}`

### 送一則訊息的完整流程

```
1. chat app 開 WS：ws://localhost:8000/ws?token=<JWT>
2. 使用者輸入 → 送 {type:"message", conversation_id, content, temp_id}
3. 後端：驗 token → 確認 sender 屬於該 conversation
        → 寫入 Message 表 → 取得 id/created_at
4. 後端回寄件人 ACK：{type:"ack", temp_id, message}
   （前端把樂觀訊息換成正式的）
5. 收件人在線 → 推 {type:"message", message} 給對方即時顯示
   收件人離線 → 不推，已存 DB，對方下次登入用 REST 撈
```

- 前端採**樂觀更新**：先顯示帶 `temp_id` 的訊息，收到 ACK 再對齊。

## 8. 錯誤處理

- **WS 斷線**：前端自動重連（指數退避），重連後用 REST 撈最新歷史補齊。
- **Token 過期**：WS 被關閉 → shell 清狀態 → 導回登入。
- **送訊息失敗（DB 錯誤）**：回 `{type:"error"}`，前端標記該訊息「未送出，可重試」。
- **重複加好友 / 加不存在的 email**：REST 回 4xx 與清楚錯誤訊息。

## 9. 安全

- 密碼用 bcrypt hash。
- JWT 含 `user_id` 與過期時間；所有 REST / WS 都驗 token。
- CORS 限定前端來源（shell/auth/chat 的 dev 與正式網域）。

## 10. 測試策略

### 後端（pytest）

- 單元：auth（hash/JWT）、conversation 排序邏輯。
- 整合：REST 端點。
- WebSocket：用 FastAPI `TestClient` 測連線驗證與訊息收發落庫。

### 前端（Vitest + Testing Library）

- auth 表單驗證與送出。
- 訊息列表渲染。
- 樂觀更新邏輯。
- 各 remote 元件可獨立測（邊界清楚的好處）。
