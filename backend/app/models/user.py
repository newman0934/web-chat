import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    """使用者。email 唯一且建索引（登入與加好友都以 email 查詢）。"""

    __tablename__ = "users"

    # 用通用 Uuid 型別（非 postgresql.UUID），Postgres 與測試用 SQLite 皆可用。
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt hash，不存明碼
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 最後一條 WS 連線斷開的時間;在線(有連線)時不顯示時間。NULL = 從未上線。
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
