"""serialize_conversations_out(批次)與逐筆 serialize_conversation_out 的等價性。

批次版把 list_conversations 的 N+1 收斂成固定查詢數;此測試保證其輸出與逐筆版相同
(成員順序不保證,故以 id 排序後比較),並順帶驗證未讀/已讀/最後訊息/已刪語意正確。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Message, MessageRead, User
from app.services.conversations import (
    create_group_conversation,
    get_or_create_direct_conversation,
)
from app.services.conversation_serializers import (
    serialize_conversation_out,
    serialize_conversations_out,
)


def _norm(co):
    d = co.model_dump(mode="json")
    d["members"] = sorted(d["members"], key=lambda m: m["id"])
    return d


@pytest.mark.asyncio
async def test_serialize_conversations_batch_matches_per_conv(session_factory):
    async with session_factory() as db:
        def mk(name: str) -> User:
            u = User(
                email=f"{name}-{uuid.uuid4().hex[:6]}@example.com",
                display_name=name,
                password_hash="x",
            )
            db.add(u)
            return u

        me, alice, bob, carol = mk("Me"), mk("Alice"), mk("Bob"), mk("Carol")
        await db.flush()

        d1 = await get_or_create_direct_conversation(db, me.id, alice.id)
        g1 = await create_group_conversation(db, me.id, "群組", [bob.id, carol.id])
        d2 = await get_or_create_direct_conversation(db, me.id, carol.id)  # 無訊息對話
        await db.flush()

        base = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)

        def msg(conv, sender, content, mins, deleted=False) -> Message:
            m = Message(conversation_id=conv.id, sender_id=sender.id, content=content)
            m.created_at = base + timedelta(minutes=mins)
            if deleted:
                m.deleted_at = base + timedelta(minutes=mins, seconds=30)
            db.add(m)
            return m

        a1 = msg(d1, alice, "hi", 1)
        msg(d1, me, "yo", 2)
        a2 = msg(d1, alice, "there", 5)   # d1 最後一則
        b1 = msg(g1, bob, "grp1", 3)
        msg(g1, me, "to-delete", 6, deleted=True)  # g1 最後一則(已刪)
        await db.flush()
        db.add(MessageRead(message_id=a1.id, user_id=me.id))     # me 讀了 a1(a2 仍未讀)
        db.add(MessageRead(message_id=b1.id, user_id=carol.id))  # carol 讀了 b1
        await db.commit()

        convs = [d1, g1, d2]
        batched = await serialize_conversations_out(db, convs, me)
        per = [await serialize_conversation_out(db, c, me) for c in convs]

        # 等價(成員以 id 排序後逐筆相同)
        assert [_norm(x) for x in batched] == [_norm(x) for x in per]

        # 語意正確(避免兩版同壞的恆等假象)
        by = {x.id: x for x in batched}
        assert by[d1.id].last_message.content == "there"
        assert by[d1.id].unread_count == 1
        assert by[g1.id].last_message.deleted is True
        assert by[g1.id].last_message.content == ""
        assert by[g1.id].unread_count == 1  # b1(bob 送、me 未讀)
        assert by[d2.id].last_message is None
        assert by[d2.id].unread_count == 0
