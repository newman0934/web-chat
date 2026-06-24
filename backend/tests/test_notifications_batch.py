"""serialize_notifications(批次)與逐筆 serialize_notification 的等價性。"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Message, User
from app.services import notifications as svc


@pytest.mark.asyncio
async def test_serialize_notifications_batch_matches_singular(session_factory):
    async with session_factory() as db:
        def mk(n):
            u = User(email=f"{n}-{uuid.uuid4().hex[:6]}@example.com", display_name=n, password_hash="x")
            db.add(u)
            return u

        me, a1, a2 = mk("Me"), mk("Actor1"), mk("Actor2")
        await db.flush()
        conv = uuid.uuid4()
        live = Message(conversation_id=conv, sender_id=me.id, content="原文內容")
        gone = Message(conversation_id=conv, sender_id=me.id, content="要刪的")
        db.add_all([live, gone])
        await db.flush()
        gone.deleted_at = datetime.now(timezone.utc)
        n1 = await svc.create_notification(
            db, user_id=me.id, type="reply", actor_id=a1.id, conversation_id=conv, message_id=live.id,
        )
        n2 = await svc.create_notification(
            db, user_id=me.id, type="reaction", actor_id=a2.id, conversation_id=conv, message_id=gone.id, emoji="👍",
        )
        await db.commit()

        notifs = await svc.list_notifications(db, me.id, limit=50)
        batched = await svc.serialize_notifications(db, notifs)
        per = [await svc.serialize_notification(db, n) for n in notifs]
        assert batched == per

        by = {d["id"]: d for d in batched}
        assert by[str(n1.id)]["actor"]["display_name"] == "Actor1"
        assert by[str(n1.id)]["message_preview"] == "原文內容"
        assert by[str(n2.id)]["message_preview"] == ""  # 被互動訊息已刪 → 摘要空
        assert by[str(n2.id)]["emoji"] == "👍"
