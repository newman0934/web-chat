"""站內通知測試。

Task 1：Notification model 落庫 roundtrip（schema 由 conftest 的 create_all 建立）。
後續 task 會在此檔補 service / WS 觸發 / REST 的測試。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Message, Notification, User
from app.services import notifications as svc


async def _mk_user(db, name: str) -> User:
    u = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@e2e.test",
        display_name=name,
        password_hash="x",
    )
    db.add(u)
    await db.flush()
    return u


async def _mk_message(db, *, sender_id, conversation_id, content="hi", deleted=False) -> Message:
    m = Message(conversation_id=conversation_id, sender_id=sender_id, content=content)
    if deleted:
        m.deleted_at = datetime.now(timezone.utc)
    db.add(m)
    await db.flush()
    return m


@pytest.mark.asyncio
async def test_notification_model_roundtrip(session_factory):
    """可建立並讀回一筆 Notification，預設未讀（read_at 為 None）、有 created_at。"""
    async with session_factory() as db:
        n = Notification(
            user_id=uuid.uuid4(),
            type="reaction",
            actor_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            emoji="👍",
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)

    assert n.id is not None
    assert n.type == "reaction"
    assert n.emoji == "👍"
    assert n.read_at is None
    assert n.created_at is not None


# ── Task 2: service ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_notification_skips_self(session_factory):
    """user_id == actor_id（對自己的訊息互動）→ 不建立。"""
    async with session_factory() as db:
        me = uuid.uuid4()
        n = await svc.create_notification(
            db, user_id=me, type="reply", actor_id=me,
            conversation_id=uuid.uuid4(), message_id=uuid.uuid4(),
        )
        assert n is None
        assert await svc.unread_count(db, me) == 0


@pytest.mark.asyncio
async def test_serialize_carries_emoji_and_masks_deleted(session_factory):
    """serialize 帶 actor 名與 emoji；被互動訊息已刪 → message_preview 為空。"""
    async with session_factory() as db:
        recipient = await _mk_user(db, "Recipient")
        actor = await _mk_user(db, "Actor")
        conv = uuid.uuid4()
        live = await _mk_message(db, sender_id=recipient.id, conversation_id=conv, content="原文內容")
        n = await svc.create_notification(
            db, user_id=recipient.id, type="reaction", actor_id=actor.id,
            conversation_id=conv, message_id=live.id, emoji="👍",
        )
        await db.commit()
        d = await svc.serialize_notification(db, n)
        assert d["type"] == "reaction"
        assert d["emoji"] == "👍"
        assert d["actor"]["display_name"] == "Actor"
        assert d["message_preview"] == "原文內容"
        assert d["read"] is False

        gone = await _mk_message(db, sender_id=recipient.id, conversation_id=conv, content="要刪的", deleted=True)
        n2 = await svc.create_notification(
            db, user_id=recipient.id, type="reply", actor_id=actor.id,
            conversation_id=conv, message_id=gone.id,
        )
        await db.commit()
        d2 = await svc.serialize_notification(db, n2)
        assert d2["message_preview"] == ""


@pytest.mark.asyncio
async def test_list_order_unread_and_mark_read_scoped(session_factory):
    """列表新→舊;未讀數;標已讀只動「自己 + 該對話」。"""
    async with session_factory() as db:
        me = await _mk_user(db, "Me")
        other = await _mk_user(db, "Other")
        actor = await _mk_user(db, "Actor")
        convA, convB = uuid.uuid4(), uuid.uuid4()
        base = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)

        # me：convA 兩筆、convB 一筆;other：convA 一筆(不該被我標到)
        async def add(user, conv, mins):
            msg = await _mk_message(db, sender_id=user, conversation_id=conv)
            n = await svc.create_notification(
                db, user_id=user, type="reply", actor_id=actor.id,
                conversation_id=conv, message_id=msg.id,
            )
            n.created_at = base + timedelta(minutes=mins)
            return n

        await add(me.id, convA, 1)
        await add(me.id, convA, 3)
        await add(me.id, convB, 2)
        await add(other.id, convA, 1)
        await db.commit()

        # 列表新→舊
        items = await svc.list_notifications(db, me.id, limit=10)
        times = [n.created_at for n in items]
        assert times == sorted(times, reverse=True)
        assert len(items) == 3
        assert await svc.unread_count(db, me.id) == 3

        # 標 me 的 convA → 只動 2 筆
        marked = await svc.mark_conversation_read(db, me.id, convA)
        await db.commit()
        assert marked == 2
        assert await svc.unread_count(db, me.id) == 1   # convB 仍未讀
        assert await svc.unread_count(db, other.id) == 1  # other 不受影響
