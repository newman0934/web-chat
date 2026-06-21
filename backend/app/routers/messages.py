"""單則訊息層級的 REST 端點（目前：編輯歷史）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Message, MessageEdit, User
from app.schemas import MessageVersionOut
from app.services.conversations import get_conversation_for_member

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/{message_id}/edits", response_model=list[MessageVersionOut])
async def list_message_edits(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="查無此訊息")
    conv = await get_conversation_for_member(db, msg.conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此訊息或無權限")
    if msg.deleted_at is not None:
        raise HTTPException(status_code=403, detail="訊息已刪除，無法檢視編輯歷史")

    rows = await db.execute(
        select(MessageEdit)
        .where(MessageEdit.message_id == message_id)
        .order_by(MessageEdit.created_at)
    )
    versions = [
        MessageVersionOut(content=e.content, created_at=e.created_at)
        for e in rows.scalars().all()
    ]
    # 目前版本當最後一筆（生效時間 = edited_at 或原始 created_at）。
    versions.append(
        MessageVersionOut(content=msg.content, created_at=msg.edited_at or msg.created_at)
    )
    return versions
