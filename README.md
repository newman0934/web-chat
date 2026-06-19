# chat-web

Web 版 1對1 即時通訊軟體 MVP。前端採微前端（Module Federation），後端 FastAPI。

設計文件：[docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md](docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md)

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

- Node 18+（前端）
- Python 3.11+（後端）
- Docker（PostgreSQL；或自備本地 Postgres）

## 啟動後端

```bash
# 1. 起 Postgres
docker compose up -d db

# 2. 安裝相依與遷移
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head

# 3. 起 API
uvicorn app.main:app --reload --port 8000
```

後端測試：

```bash
cd backend
pytest
```

## 啟動前端

三個 app 各自獨立。先起 remote，再起 host。

```bash
# auth remote
cd frontend/auth && npm install && npm run dev   # :5001

# chat remote
cd frontend/chat && npm install && npm run dev    # :5002

# shell host
cd frontend/shell && npm install && npm run dev   # :5000
```

開 http://localhost:5000 。

> 微前端的「獨立部署」展示：`npm run build` 各 remote 產生 `remoteEntry.js`，shell 透過 URL 載入。
