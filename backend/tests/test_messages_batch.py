"""serialize_messages_out(批次)與逐則 serialize_message_out 的等價性。

批次版把 list_messages 的 per-message N+1(附件/表情/已讀/回覆/轉發)收斂成固定查詢數;
此測試保證輸出與逐則版相同(表情分組順序不保證,正規化後比較),並驗證各情境語意正確。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Attachment, Message, MessageRead, Reaction, User
from app.services.conversations import create_group_conversation
from app.services.conversation_serializers import (
    serialize_message_out,
    serialize_messages_out,
)


def _norm(mo):
    d = mo.model_dump(mode="json")
    d["reactions"] = sorted(
        ({**g, "user_ids": sorted(g["user_ids"])} for g in d["reactions"]),
        key=lambda g: g["emoji"],
    )
    return d


@pytest.mark.asyncio
async def test_serialize_messages_batch_matches_per_message(session_factory):
    async with session_factory() as db:
        def mk(name: str) -> User:
            u = User(
                email=f"{name}-{uuid.uuid4().hex[:6]}@example.com",
                display_name=name,
                password_hash="x",
            )
            db.add(u)
            return u

        me, alice, bob = mk("Me"), mk("Alice"), mk("Bob")
        await db.flush()
        conv = await create_group_conversation(db, me.id, "G", [alice.id, bob.id])
        await db.flush()

        base = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)

        def msg(sender, content, mins, *, deleted=False, reply_to=None, fwd=None) -> Message:
            m = Message(
                conversation_id=conv.id, sender_id=sender.id, content=content,
                reply_to_message_id=reply_to, forwarded_from_user_id=fwd,
            )
            m.created_at = base + timedelta(minutes=mins)
            if deleted:
                m.deleted_at = base + timedelta(minutes=mins, seconds=30)
            db.add(m)
            return m

        m1 = msg(alice, "hello", 1)                       # 純文字
        m2 = msg(me, "with-att", 2)                       # 帶附件
        m3 = msg(bob, "reacted", 3)                       # 多人表情
        await db.flush()
        m4 = msg(me, "reply-to-m1", 4, reply_to=m1.id)    # 回覆未刪訊息
        m5 = msg(me, "forwarded", 5, fwd=bob.id)          # 轉發來源
        m6 = msg(alice, "to-be-deleted", 6, deleted=True)  # 已刪訊息
        await db.flush()
        m7 = msg(me, "reply-to-deleted", 7, reply_to=m6.id)  # 回覆已刪訊息
        await db.flush()

        db.add(Attachment(
            message_id=m2.id, uploader_id=me.id, stored_name="x",
            original_name="pic.png", content_type="image/png", size=3, is_image=True,
        ))
        db.add(Reaction(message_id=m3.id, user_id=alice.id, emoji="👍"))
        db.add(Reaction(message_id=m3.id, user_id=bob.id, emoji="👍"))
        db.add(Reaction(message_id=m3.id, user_id=me.id, emoji="❤️"))
        db.add(MessageRead(message_id=m1.id, user_id=bob.id))   # m1 已讀數=1
        db.add(MessageRead(message_id=m3.id, user_id=alice.id))  # m3 已讀數=1
        await db.commit()

        page = [m1, m2, m3, m4, m5, m6, m7]
        batched = await serialize_messages_out(db, page)
        per = [await serialize_message_out(db, m) for m in page]

        # 等價(表情正規化後逐則相同)
        assert [_norm(x) for x in batched] == [_norm(x) for x in per]

        # 語意正確(避免兩版同壞的恆等假象)
        by = {x.id: x for x in batched}
        assert by[m1.id].read_count == 1
        assert by[m2.id].attachment is not None and by[m2.id].attachment.original_name == "pic.png"
        r = {g.emoji: g for g in by[m3.id].reactions}
        assert r["👍"].count == 2 and set(r["👍"].user_ids) == {alice.id, bob.id}
        assert r["❤️"].count == 1
        assert by[m4.id].reply_to.content == "hello" and by[m4.id].reply_to.sender_id == alice.id
        assert by[m4.id].reply_to.deleted is False
        assert by[m5.id].forwarded_from.id == bob.id and by[m5.id].forwarded_from.display_name == "Bob"
        assert by[m6.id].deleted is True and by[m6.id].content == ""
        assert by[m7.id].reply_to.deleted is True
        assert by[m7.id].reply_to.content == "" and by[m7.id].reply_to.has_attachment is False
