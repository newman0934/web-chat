"""線上狀態(presence)的集中後端邏輯:好友查詢、最後上線時間、事件序列化。

online 本身來自記憶體的 ConnectionManager(見 app/ws/manager.py);這裡只處理需要
DB 與序列化的部分。last_seen_at 一律經 to_utc_iso 輸出,避免 SQLite naive 錯位。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact, User
from app.timeutils import to_utc_iso


async def get_friend_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """某使用者的好友 id 集合(單向 Contact 即代表好友,加好友時成對建立)。"""
    res = await db.execute(
        select(Contact.contact_user_id).where(Contact.user_id == user_id)
    )
    return set(res.scalars().all())


async def set_last_seen(db: AsyncSession, user_id: uuid.UUID) -> datetime:
    """把某使用者的 last_seen_at 寫成現在時間並回傳(tz-aware UTC)。呼叫端負責 commit。"""
    now = datetime.now(timezone.utc)
    user = await db.get(User, user_id)
    if user is not None:
        user.last_seen_at = now
    return now


def build_presence_event(
    user_id: uuid.UUID, online: bool, last_seen_at: datetime | None
) -> dict:
    """組 server→client 的 presence 事件(JSON-ready)。online 時 last_seen_at 通常為 None。"""
    return {
        "type": "presence",
        "user_id": str(user_id),
        "online": online,
        "last_seen_at": to_utc_iso(last_seen_at),
    }


async def presence_for_contacts(
    db: AsyncSession, contact_ids: set[uuid.UUID]
) -> dict[uuid.UUID, datetime | None]:
    """批次取每個 contact 的 last_seen_at(未設者為 None),供 GET /contacts 快照。"""
    if not contact_ids:
        return {}
    res = await db.execute(
        select(User.id, User.last_seen_at).where(User.id.in_(contact_ids))
    )
    return {row[0]: row[1] for row in res.all()}
