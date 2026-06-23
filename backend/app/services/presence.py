"""線上狀態(presence)的集中後端邏輯:好友查詢與事件序列化。

online 與 last_seen 都來自記憶體的 ConnectionManager(見 app/ws/manager.py)——presence
刻意是 in-memory、單程序。此處只負責「查好友」(需 DB)與「組事件」(純函式),
不寫 DB。last_seen_at 一律經 to_utc_iso 輸出,避免 SQLite naive 錯位。
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contact
from app.timeutils import to_utc_iso


async def get_friend_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """某使用者的好友 id 集合(單向 Contact 即代表好友,加好友時成對建立)。"""
    res = await db.execute(
        select(Contact.contact_user_id).where(Contact.user_id == user_id)
    )
    return set(res.scalars().all())


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
