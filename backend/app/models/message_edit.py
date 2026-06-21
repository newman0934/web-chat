import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessageEdit(Base):
    """訊息的某個歷史版本（被後續編輯取代前的內容）。

    每次編輯前，把「目前 content + 它的生效時間」快照成一列；
    歷史 = 這些列（由舊到新）＋ 目前的 Message.content。
    """

    __tablename__ = "message_edits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # created_at 顯式帶入（= 該版本生效時間），故不設 server_default。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
