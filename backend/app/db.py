"""資料庫連線：async engine、session factory，以及 FastAPI 依賴。"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM model 的共同基底；Alembic 也透過 Base.metadata 產生遷移。"""


_settings = get_settings()
engine = create_async_engine(_settings.database_url, echo=False, future=True)
# expire_on_commit=False：commit 後物件屬性仍可讀，避免 async 情境下意外的 lazy load。
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依賴：每個請求開一個 session，結束自動關閉。

    注意：WebSocket 端點不走這個依賴，而是直接用 SessionLocal（見 app/ws/router.py），
    以便測試能 monkeypatch session factory。
    """
    async with SessionLocal() as session:
        yield session
