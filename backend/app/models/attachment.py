import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Attachment(Base):
    """訊息附件中繼資料。上傳時建立（message_id=NULL），送訊息時綁定。

    一則訊息可有多個附件(一對多);依訊息查附件以 message_id 索引。
    """

    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 同一則訊息內的附件顯示順序(綁定時依 attachment_ids 順序設 0,1,2...)。
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
