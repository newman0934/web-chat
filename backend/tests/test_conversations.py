import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Message

pytestmark = pytest.mark.asyncio


async def _setup_pair(client, register_user, auth_headers):
    alice = await register_user("ca@example.com", "Alice")
    bob = await register_user("cb@example.com", "Bob")
    resp = await client.post(
        "/contacts", json={"email": "cb@example.com"}, headers=auth_headers(alice)
    )
    conv_id = resp.json()["conversation_id"]
    me_a = await client.get("/users/me", headers=auth_headers(alice))
    me_b = await client.get("/users/me", headers=auth_headers(bob))
    return alice, bob, me_a.json()["id"], me_b.json()["id"], conv_id


async def test_conversation_list_last_message_and_unread(
    client, register_user, auth_headers, session_factory
):
    alice, bob, alice_id, bob_id, conv_id = await _setup_pair(
        client, register_user, auth_headers
    )

    base = datetime.now(timezone.utc)
    async with session_factory() as s:
        # Bob 傳 2 則給 Alice（對 Alice 而言未讀）
        s.add(Message(conversation_id=uuid.UUID(conv_id), sender_id=uuid.UUID(bob_id),
                      content="hi", created_at=base))
        s.add(Message(conversation_id=uuid.UUID(conv_id), sender_id=uuid.UUID(bob_id),
                      content="there", created_at=base + timedelta(seconds=1)))
        await s.commit()

    resp = await client.get("/conversations", headers=auth_headers(alice))
    assert resp.status_code == 200
    convs = resp.json()
    assert len(convs) == 1
    assert convs[0]["other_user"]["email"] == "cb@example.com"
    assert convs[0]["last_message"]["content"] == "there"
    assert convs[0]["unread_count"] == 2


async def test_messages_pagination(
    client, register_user, auth_headers, session_factory
):
    alice, bob, alice_id, bob_id, conv_id = await _setup_pair(
        client, register_user, auth_headers
    )
    base = datetime.now(timezone.utc)
    async with session_factory() as s:
        for i in range(5):
            s.add(Message(conversation_id=uuid.UUID(conv_id),
                          sender_id=uuid.UUID(alice_id), content=f"m{i}",
                          created_at=base + timedelta(seconds=i)))
        await s.commit()

    page = await client.get(
        f"/conversations/{conv_id}/messages?limit=2", headers=auth_headers(alice)
    )
    assert page.status_code == 200
    msgs = page.json()
    assert [m["content"] for m in msgs] == ["m3", "m4"]  # 最新兩則，由舊到新
    # 新格式：有 read_count 欄位，沒有 read_at
    assert "read_count" in msgs[0]
    assert "read_at" not in msgs[0]

    oldest = msgs[0]["created_at"]
    prev = await client.get(
        f"/conversations/{conv_id}/messages?limit=2&before={oldest}",
        headers=auth_headers(alice),
    )
    assert [m["content"] for m in prev.json()] == ["m1", "m2"]


async def test_messages_forbidden_for_outsider(
    client, register_user, auth_headers
):
    _, _, _, _, conv_id = await _setup_pair(client, register_user, auth_headers)
    outsider = await register_user("out@example.com", "Out")
    resp = await client.get(
        f"/conversations/{conv_id}/messages", headers=auth_headers(outsider)
    )
    assert resp.status_code == 404
