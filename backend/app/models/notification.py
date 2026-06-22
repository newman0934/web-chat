import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Notification(Base):
    """站內通知：別人對「你的訊息」做了 reply / reaction / forward。

    收件人 = 被互動訊息的 sender（user_id）。一事件一筆；不通知自己（建立端守門）。
    開啟 conversation_id 對應對話時整批標已讀（read_at）。
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # 列表分頁（某使用者、新→舊）；未讀數以 user_id + read_at IS NULL 過濾。
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 收件人。
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # reply|reaction|forward
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 你那則被互動訊息所在的對話（點擊導向 + 開啟即已讀）。
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # 你「被互動」的那則訊息。
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 僅 reaction
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
