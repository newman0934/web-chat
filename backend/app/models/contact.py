import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Contact(Base):
    """好友關係。加好友時建立「雙向」兩筆（A→B 與 B→A），方便各自查自己的好友清單。

    UNIQUE(user_id, contact_user_id) 防止重複加同一人。
    """

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("user_id", "contact_user_id", name="uq_contact_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    contact_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
