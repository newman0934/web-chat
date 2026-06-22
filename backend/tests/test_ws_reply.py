"""Tests for reply_to_message_id validation and storage in _handle_send."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


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
# Test 1: Reply to a message in the SAME conversation — ack/broadcast correct
# ---------------------------------------------------------------------------

async def test_reply_same_conversation(client, register_user, auth_headers, session_factory):
    """Replying to a message in the same conversation succeeds.

    Both the ack (to sender) and broadcast (to recipient) must contain
    a `reply_to` dict with the correct id, sender_id, and content.
    """
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    # Alice sends a message that Bob will later reply to.
    orig_id = await _insert_message(session_factory, conv_id, alice_id, content="original msg")

    with TestClient(app) as tc:
        with (
            tc.websocket_connect(f"/ws?token={alice}") as wa,
            tc.websocket_connect(f"/ws?token={bob}") as wb,
        ):
            # Bob replies to Alice's message.
            wb.send_json({
                "type": "message",
                "conversation_id": conv_id,
                "content": "reply text",
                "temp_id": "t-1",
                "reply_to_message_id": orig_id,
            })
            ack = wb.receive_json()  # ack → Bob (sender)
            broadcast = wa.receive_json()  # message → Alice (recipient)

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
# Test 2: reply_to_message_id from a DIFFERENT conversation → invalid_reply
# ---------------------------------------------------------------------------

async def test_reply_cross_conversation_rejected(client, register_user, auth_headers, session_factory):
    """reply_to_message_id from a different conversation must be rejected
    with reason='invalid_reply', and NO new Message should be persisted.
    """
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )

    # Carol is a third user; she has a separate conversation with Alice.
    carol = await register_user("rpc@example.com", "Carol")
    await client.post("/contacts", json={"email": "rpc@example.com"}, headers=auth_headers(alice))
    other_convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    other_conv_id = next(c["id"] for c in other_convs if c["id"] != conv_id)

    # Insert a message in the OTHER conversation (Alice ↔ Carol).
    other_msg_id = await _insert_message(session_factory, other_conv_id, alice_id, content="in other conv")

    # Count messages in alice↔bob conversation before the attempt.
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
            err = wb.receive_json()

    assert err["type"] == "error"
    assert err["reason"] == "invalid_reply"
    assert err.get("temp_id") == "t-cross"

    # Verify no new message was persisted.
    async with session_factory() as s:
        result = await s.execute(
            select(Message).where(Message.conversation_id == uuid.UUID(conv_id))
        )
        after_count = len(result.scalars().all())
    assert after_count == before_count


# ---------------------------------------------------------------------------
# Test 3: Reply to a soft-deleted message → invalid_reply
# ---------------------------------------------------------------------------

async def test_reply_to_soft_deleted_message_rejected(client, register_user, auth_headers, session_factory):
    """Replying to a message that has been soft-deleted must return invalid_reply."""
    alice, bob, conv_id, alice_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    orig_id = await _insert_message(session_factory, conv_id, alice_id, content="will be deleted")

    # Soft-delete the original message directly in DB.
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
            err = wb.receive_json()

    assert err["type"] == "error"
    assert err["reason"] == "invalid_reply"
    assert err.get("temp_id") == "t-del"


# ---------------------------------------------------------------------------
# Test 4: Malformed reply_to_message_id (not a UUID) → invalid_payload
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
            err = wb.receive_json()

    assert err["type"] == "error"
    assert err["reason"] == "invalid_payload"
    assert err.get("temp_id") == "t-bad"
