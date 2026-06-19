import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Conversation(Base):
    """1對1（type='direct'，2 成員）或群組（type='group'，N 成員）對話。"""

    __tablename__ = "conversations"
    __table_args__ = (
        # direct 對話以正規化的 direct_key 保證同兩人唯一；group 的 direct_key 為 NULL。
        UniqueConstraint("direct_key", name="uq_conversation_direct_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    direct_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
