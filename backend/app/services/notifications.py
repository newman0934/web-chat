"""站內通知的集中邏輯：建立、序列化、查詢、標已讀。WS 與 REST 兩端共用。

序列化回傳 JSON-ready dict（uuid → str、datetime → ISO），WS 可直接 send_json，
REST 端的 NotificationOut 也能由它驗證（Pydantic 會把 str 轉回 uuid/datetime）。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Notification, User

# 通知列表的訊息摘要長度。
PREVIEW_LEN = 50


def _iso(dt: datetime | None) -> str | None:
    """tz-safe ISO 字串：naive（SQLite 回傳）視為 UTC，避免 astimezone 用到本機時區。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    actor_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    emoji: str | None = None,
) -> Notification | None:
    """建立一筆通知並 add 到 session（呼叫端負責 commit）。

    對自己的訊息互動（user_id == actor_id）不建立，回 None。
    """
    if user_id == actor_id:
        return None
    n = Notification(
        user_id=user_id,
        type=type,
        actor_id=actor_id,
        conversation_id=conversation_id,
        message_id=message_id,
        emoji=emoji,
    )
    db.add(n)
    return n


async def serialize_notification(db: AsyncSession, n: Notification) -> dict:
    """組 JSON-ready 通知 dict（含 actor 名與被互動訊息摘要；已刪訊息摘要為空）。"""
    actor = await db.get(User, n.actor_id)
    msg = await db.get(Message, n.message_id)
    deleted = msg is not None and msg.deleted_at is not None
    preview = "" if (msg is None or deleted) else (msg.content or "")[:PREVIEW_LEN]
    return {
        "id": str(n.id),
        "type": n.type,
        "actor": {
            "id": str(n.actor_id),
            "display_name": actor.display_name if actor else "",
        },
        "conversation_id": str(n.conversation_id),
        "message_id": str(n.message_id),
        "message_preview": preview,
        "emoji": n.emoji,
        "read": n.read_at is not None,
        "created_at": _iso(n.created_at),
    }


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    before: datetime | None = None,
    limit: int = 20,
) -> list[Notification]:
    """某使用者的通知（新→舊、before 游標、limit）。"""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if before is not None:
        stmt = stmt.where(Notification.created_at < before)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """某使用者未讀（read_at IS NULL）的通知數。"""
    res = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(res.scalar_one())


async def mark_conversation_read(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> int:
    """把某使用者、某對話下所有未讀通知標已讀；回標記筆數（呼叫端負責 commit）。"""
    now = datetime.now(timezone.utc)
    res = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.conversation_id == conversation_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    return res.rowcount or 0
