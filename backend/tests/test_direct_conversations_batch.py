"""get_or_create_direct_conversations(批次)的正確性:既有重用、缺漏補建、冪等。"""

import uuid

import pytest

from app.models import User
from app.services.conversations import (
    direct_key,
    get_or_create_direct_conversation,
    get_or_create_direct_conversations,
)


@pytest.mark.asyncio
async def test_get_or_create_direct_conversations_batch(session_factory):
    async with session_factory() as db:
        def mk(n):
            u = User(email=f"{n}-{uuid.uuid4().hex[:6]}@example.com", display_name=n, password_hash="x")
            db.add(u)
            return u

        me, a, b, c = mk("Me"), mk("A"), mk("B"), mk("C")
        await db.flush()

        # 預先為 a 建好 direct(模擬加好友時就建);b、c 尚無。
        existing = await get_or_create_direct_conversation(db, me.id, a.id)
        await db.flush()

        convs = await get_or_create_direct_conversations(db, me.id, [a.id, b.id, c.id])
        assert convs[a.id].id == existing.id                      # 既有 → 重用,不重建
        assert convs[b.id].direct_key == direct_key(me.id, b.id)  # 缺漏 → 補建
        assert convs[c.id].direct_key == direct_key(me.id, c.id)
        await db.flush()

        # 冪等:再呼叫拿到同一批,不重建。
        again = await get_or_create_direct_conversations(db, me.id, [a.id, b.id, c.id])
        assert {o: cv.id for o, cv in again.items()} == {o: cv.id for o, cv in convs.items()}

        assert await get_or_create_direct_conversations(db, me.id, []) == {}
