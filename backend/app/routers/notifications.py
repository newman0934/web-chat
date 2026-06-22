"""站內通知 REST：列表(含未讀數)與標已讀。

已讀的唯一來源是「開啟對話」→ POST /notifications/read {conversation_id}。
列表只回自己的;標已讀也只動自己的(故對非自己對話 marked=0、不洩漏存在性)。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.schemas import MarkReadRequest, NotificationListOut
from app.services import notifications as svc
from app.timeutils import coerce_cursor

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    before: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notifs = await svc.list_notifications(db, current_user.id, before=coerce_cursor(db, before), limit=limit)
    items = [await svc.serialize_notification(db, n) for n in notifs]
    unread = await svc.unread_count(db, current_user.id)
    return {"items": items, "unread_count": unread}


@router.post("/read")
async def mark_read(
    payload: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    marked = await svc.mark_conversation_read(db, current_user.id, payload.conversation_id)
    await db.commit()
    return {"ok": True, "marked": marked}
