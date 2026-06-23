"""Tests for reply_to_message_id validation and storage in _handle_send."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio

def _recv(ws):
    """收下一個非 presence frame(presence 為好友上/下線廣播,與本檔測試無關)。"""
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "presence":
            return msg



async def _setup_pair(client, register_user, auth_headers, session_factory):
    """Register Alice & Bob, make them contacts, return tokens + conv_id."""
    alice = await register_user("rpa@example.com", "Alice")
    bob = await register_user("rpb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rpb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    return alice, bob, conv["id"], aid


async def _insert_message(session_factory, conv_id: str, sender_id: str, content: str = "hello") -> str:
    """Directly insert a Message into DB and return its str id."""
    async with session_factory() as s:
        m = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(sender_id),
            content=content,
        )
        s.add(m)
        await s.commit()
        return str(m.id)


# ---------------------------------------------------------------------------
# 測試 1:回覆「同一對話」內的訊息 —— ack/broadcast 正確
# ---------------------------------------------------------------------------

async def test_reply_same_conversation(client, register_user, auth_headers, session_factory):
    """Replying to a message in the same conversation succeeds.

    Both the ack (to sender) and broadcast (to recipient) must contain
    a `reply_to` dict with the correct id, sender_id, and content.
    """
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    # Alice 送出一則訊息,稍後 Bob 會回覆它。
    orig_id = await _insert_message(session_factory, conv_id, alice_id, content="original msg")

    with TestClient(app) as tc:
        with (
            tc.websocket_connect(f"/ws?token={alice}") as wa,
            tc.websocket_connect(f"/ws?token={bob}") as wb,
        ):
            # Bob 回覆 Alice 的訊息。
            wb.send_json({
                "type": "message",
                "conversation_id": conv_id,
                "content": "reply text",
                "temp_id": "t-1",
                "reply_to_message_id": orig_id,
            })
            ack = _recv(wb)  # ack → Bob (sender)
            broadcast = _recv(wa)  # message → Alice (recipient)

    assert ack["type"] == "ack"
    assert ack["temp_id"] == "t-1"
    reply_to = ack["message"]["reply_to"]
    assert reply_to is not None
    assert reply_to["id"] == orig_id
    assert reply_to["sender_id"] == alice_id
    assert reply_to["content"] == "original msg"
    assert reply_to["deleted"] is False

    assert broadcast["type"] == "message"
    b_reply_to = broadcast["message"]["reply_to"]
    assert b_reply_to is not None
    assert b_reply_to["id"] == orig_id
    assert b_reply_to["sender_id"] == alice_id
    assert b_reply_to["content"] == "original msg"


# ---------------------------------------------------------------------------
# 測試 2:reply_to_message_id 來自「不同對話」→ invalid_reply
# ---------------------------------------------------------------------------

async def test_reply_cross_conversation_rejected(client, register_user, auth_headers, session_factory):
    """reply_to_message_id from a different conversation must be rejected
    with reason='invalid_reply', and NO new Message should be persisted.
    """
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )

    # Carol 是第三位使用者;她與 Alice 另有一個對話。
    carol = await register_user("rpc@example.com", "Carol")
    await client.post("/contacts", json={"email": "rpc@example.com"}, headers=auth_headers(alice))
    other_convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    other_conv_id = next(c["id"] for c in other_convs if c["id"] != conv_id)

    # 在「另一個」對話(Alice ↔ Carol)插入一則訊息。
    other_msg_id = await _insert_message(session_factory, other_conv_id, alice_id, content="in other conv")

    # 嘗試前先數 alice↔bob 對話的訊息數。
    async with session_factory() as s:
        result = await s.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
        )
        before_count = len(result.scalars().all())

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "message",
                "conversation_id": conv_id,
                "content": "sneaky reply",
                "temp_id": "t-cross",
                "reply_to_message_id": other_msg_id,  # belongs to other_conv!
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_reply"
    assert err.get("temp_id") == "t-cross"

    # 驗證沒有新訊息被寫入。
    async with session_factory() as s:
        result = await s.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
        )
        after_count = len(result.scalars().all())
    assert after_count == before_count


# ---------------------------------------------------------------------------
# 測試 3:回覆已軟刪的訊息 → invalid_reply
# ---------------------------------------------------------------------------

async def test_reply_to_soft_deleted_message_rejected(client, register_user, auth_headers, session_factory):
    """Replying to a message that has been soft-deleted must return invalid_reply."""
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    orig_id = await _insert_message(session_factory, conv_id, alice_id, content="will be deleted")

    # 直接在 DB 把原訊息軟刪。
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(orig_id))
        m.deleted_at = datetime.now(timezone.utc)
        await s.commit()

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "message",
                "conversation_id": conv_id,
                "content": "reply to deleted",
                "temp_id": "t-del",
                "reply_to_message_id": orig_id,
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_reply"
    assert err.get("temp_id") == "t-del"


# ---------------------------------------------------------------------------
# 測試 4:reply_to_message_id 格式錯誤(非 UUID)→ invalid_payload
# ---------------------------------------------------------------------------

async def test_reply_malformed_uuid_invalid_payload(client, register_user, auth_headers, session_factory):
    """A non-UUID reply_to_message_id must be rejected with reason='invalid_payload'."""
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "message",
                "conversation_id": conv_id,
                "content": "hello",
                "temp_id": "t-bad",
                "reply_to_message_id": "not-a-uuid",
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_payload"
    assert err.get("temp_id") == "t-bad"
