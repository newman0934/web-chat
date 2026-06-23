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
    # 保留欄位:未來的耐久化「最後上線時間」(跨重啟 / 多 worker)。
    # 目前 presence 為 in-memory、單程序,last_seen 存在 ConnectionManager(見 ws/manager.py),
    # 執行期不寫此欄位 —— 因為從 WS 生命週期寫 DB 會在 starlette TestClient 關閉路徑死結。
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
