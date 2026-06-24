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


def _notification_dict(n: Notification, actor: User | None, msg: Message | None) -> dict:
    """由通知 + 已取出的 actor / 被互動訊息組 JSON-ready dict(單一真相;已刪訊息摘要為空)。"""
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


async def serialize_notification(db: AsyncSession, n: Notification) -> dict:
    """組單一通知 dict(WS 即時推播用;會各取一次 actor / 訊息)。"""
    actor = await db.get(User, n.actor_id)
    msg = await db.get(Message, n.message_id)
    return _notification_dict(n, actor, msg)


async def serialize_notifications(db: AsyncSession, notifs: list[Notification]) -> list[dict]:
    """批次序列化一頁通知:actor 與被互動訊息各一次 IN 查詢,避免逐筆 2 個 db.get 的 N+1。"""
    if not notifs:
        return []
    actor_ids = {n.actor_id for n in notifs}
    msg_ids = {n.message_id for n in notifs}
    actors = {
        u.id: u for u in
        (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
    }
    msgs = {
        m.id: m for m in
        (await db.execute(select(Message).where(Message.id.in_(msg_ids)))).scalars().all()
    }
    return [_notification_dict(n, actors.get(n.actor_id), msgs.get(n.message_id)) for n in notifs]


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
