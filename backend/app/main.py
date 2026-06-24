"""FastAPI 應用進入點：組裝 CORS、各 REST router 與 WebSocket router。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_config import configure_logging, log_requests
from app.routers import (
    auth,
    contacts,
    conversations,
    group_management,
    messages,
    notifications,
    search,
    uploads,
    users,
)
from app.ws import router as ws_router

settings = get_settings()
settings.ensure_secure()  # 正式環境若未覆寫 JWT_SECRET 等預設值，於此直接啟動失敗
configure_logging()

app = FastAPI(title="chat-web API", version="0.1.0")

# HTTP 請求記錄(method/path/status/耗時;不含 query)。WebSocket 不經此 middleware。
app.middleware("http")(log_requests)

# 限定前端三個 app（shell/auth/chat）的來源，避免任意網站呼叫本 API。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載各功能模組的路由（前綴定義在各 router 內）。
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(contacts.router)
app.include_router(conversations.router)
app.include_router(group_management.router)
app.include_router(messages.router)
app.include_router(uploads.router)
app.include_router(notifications.router)
app.include_router(search.router)
app.include_router(ws_router.router)


@app.get("/health", tags=["meta"])
async def health():
    """健康檢查：供啟動探測 / Docker healthcheck 使用。"""
    return {"status": "ok"}
