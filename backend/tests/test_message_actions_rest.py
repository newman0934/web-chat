import uuid

import pytest

from app.models import Message, Reaction

pytestmark = pytest.mark.asyncio


async def _setup(client, register_user, auth_headers, session_factory):
    alice = await register_user("ma@example.com", "Alice")
    bob = await register_user("mb@example.com", "Bob")
    await client.post("/contacts", json={"email": "mb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="hi")
        s.add(m)
        await s.flush()
        s.add_all([
            Reaction(message_id=m.id, user_id=uuid.UUID(aid), emoji="👍"),
            Reaction(message_id=m.id, user_id=uuid.UUID(bid), emoji="👍"),
            Reaction(message_id=m.id, user_id=uuid.UUID(aid), emoji="❤️"),
        ])
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], aid, bid, mid


async def test_history_includes_reactions(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, aid, bid, mid = await _setup(client, register_user, auth_headers, session_factory)
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    reactions = {r["emoji"]: r for r in msgs[0]["reactions"]}
    assert reactions["👍"]["count"] == 2
    assert set(reactions["👍"]["user_ids"]) == {aid, bid}
    assert reactions["❤️"]["count"] == 1
    assert msgs[0]["edited_at"] is None
    assert msgs[0]["deleted"] is False


async def test_history_masks_deleted(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, aid, bid, mid = await _setup(client, register_user, auth_headers, session_factory)
    from datetime import datetime, timezone
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.deleted_at = datetime.now(timezone.utc)
        m.content = ""
        await s.commit()
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert msgs[0]["deleted"] is True
    assert msgs[0]["content"] == ""
    assert msgs[0]["reactions"] == []
    assert msgs[0]["attachments"] == []
