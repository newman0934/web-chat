"""Tests for forward WS message type (_handle_forward).

Covers:
- Forward a text message → new message in target conversation with forwarded_from = original author;
  broadcast received by both forwarder and another target member.
- Forward a message with attachment → new Attachment row (same stored_name) bound to new message;
  serialized payload includes attachment.
- Forward to a conversation user is NOT a member of → forbidden.
- Forward a message user CANNOT see (not in source conversation) → forbidden.
- Forward a soft-deleted message → forbidden.
- Missing to_conversation_id → invalid_payload.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.main import app
from app.models import Attachment, Message

pytestmark = pytest.mark.asyncio

def _recv(ws):
    """收下一個非 presence frame(presence 為好友上/下線廣播,與本檔測試無關)。"""
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "presence":
            return msg



# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _setup_pair(client, register_user, auth_headers, email_a="fa@example.com",
                      email_b="fb@example.com", name_a="Alice", name_b="Bob"):
    """Register two users, make them contacts, return tokens + conv_id + alice_id."""
    alice = await register_user(email_a, name_a)
    bob = await register_user(email_b, name_b)
    await client.post("/contacts", json={"email": email_b}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    alice_id = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bob_id = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    return alice, bob, conv["id"], alice_id, bob_id


async def _insert_message(session_factory, conv_id: str, sender_id: str,
                          content: str = "hello", deleted: bool = False) -> str:
    """Directly insert a Message and return its str id."""
    async with session_factory() as s:
        m = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(sender_id),
            content=content,
        )
        if deleted:
            m.deleted_at = datetime.now(timezone.utc)
        s.add(m)
        await s.commit()
        return str(m.id)


async def _insert_attachment(session_factory, message_id: str, uploader_id: str,
                             stored_name: str = "abc.png") -> str:
    """Directly insert an Attachment bound to a message and return its str id."""
    async with session_factory() as s:
        att = Attachment(
            message_id=uuid.UUID(message_id),
            uploader_id=uuid.UUID(uploader_id),
            stored_name=stored_name,
            original_name="photo.png",
            content_type="image/png",
            size=1024,
            is_image=True,
        )
        s.add(att)
        await s.commit()
        return str(att.id)


# ---------------------------------------------------------------------------
# Test 1: Forward text message → new message, forwarded_from, broadcast to both
# ---------------------------------------------------------------------------

async def test_forward_text_broadcasts_to_target_members(
    client, register_user, auth_headers, session_factory
):
    """Forward a text message: target conversation gets a new message with
    forwarded_from = original author; both forwarder AND another target member
    receive the broadcast."""
    # Alice ↔ Bob (source conversation)
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd1a@example.com", "fwd1b@example.com", "Alice", "Bob",
    )
    # Carol ↔ Bob (target conversation — Bob will forward to Carol)
    carol = await register_user("fwd1c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd1b@example.com"}, headers=auth_headers(carol))
    target_convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    target_conv_id = next(c["id"] for c in target_convs if c["id"] != src_conv_id)
    carol_id = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]

    # Alice posts the original message in src_conv
    orig_id = await _insert_message(session_factory, src_conv_id, alice_id, content="hello world")

    with TestClient(app) as tc:
        with (
            tc.websocket_connect(f"/ws?token={bob}") as wb,
            tc.websocket_connect(f"/ws?token={carol}") as wc,
        ):
            # Bob forwards Alice's message to the Bob↔Carol conversation
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                "to_conversation_id": target_conv_id,
            })

            # Both Bob (forwarder) and Carol (target member) should receive the broadcast
            evt_b = _recv(wb)
            evt_c = _recv(wc)

    for evt in (evt_b, evt_c):
        assert evt["type"] == "message"
        msg = evt["message"]
        assert msg["conversation_id"] == target_conv_id
        assert msg["content"] == "hello world"
        # forwarded_from should point to Alice (original sender)
        assert msg["forwarded_from"] is not None
        assert msg["forwarded_from"]["id"] == alice_id
        assert msg["forwarded_from"]["display_name"] == "Alice"
        # sender of the new message is Bob
        assert msg["sender_id"] == bob_id
        # no reply_to inherited
        assert msg["reply_to"] is None


# ---------------------------------------------------------------------------
# Test 2: Forward message with attachment → new Attachment row, same stored_name
# ---------------------------------------------------------------------------

async def test_forward_with_attachment_copies_attachment_row(
    client, register_user, auth_headers, session_factory
):
    """Forwarding a message that has an attachment creates a new Attachment row
    bound to the new message with the same stored_name (file is shared on disk).
    The serialized forwarded message includes the attachment."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd2a@example.com", "fwd2b@example.com", "Alice", "Bob",
    )
    carol = await register_user("fwd2c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd2b@example.com"}, headers=auth_headers(carol))
    target_convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    target_conv_id = next(c["id"] for c in target_convs if c["id"] != src_conv_id)

    # Insert original message with an attachment
    orig_id = await _insert_message(session_factory, src_conv_id, alice_id, content="with file")
    stored_name = "shared-disk-file.png"
    await _insert_attachment(session_factory, orig_id, alice_id, stored_name=stored_name)

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                "to_conversation_id": target_conv_id,
            })
            evt = _recv(wb)

    assert evt["type"] == "message"
    msg = evt["message"]
    new_msg_id = uuid.UUID(msg["id"])

    # Verify attachment in serialized payload (stored_name is not exposed; check is_image)
    assert msg["attachment"] is not None
    assert msg["attachment"]["is_image"] is True
    assert msg["attachment"]["original_name"] == "photo.png"

    # Verify a NEW Attachment row in DB bound to the new message
    async with session_factory() as s:
        result = await s.execute(
            select(Attachment).where(Attachment.message_id == new_msg_id)
        )
        new_att = result.scalar_one_or_none()
    assert new_att is not None
    assert new_att.stored_name == stored_name
    assert new_att.original_name == "photo.png"
    assert new_att.is_image is True
    # It should NOT be the same row as the original attachment
    orig_att_result = None
    async with session_factory() as s:
        result = await s.execute(
            select(Attachment).where(Attachment.message_id == uuid.UUID(orig_id))
        )
        orig_att_result = result.scalar_one_or_none()
    assert orig_att_result is not None
    assert new_att.id != orig_att_result.id  # different rows


# ---------------------------------------------------------------------------
# Test 3: Forward to a conversation the user is NOT a member of → forbidden
# ---------------------------------------------------------------------------

async def test_forward_to_non_member_conversation_forbidden(
    client, register_user, auth_headers, session_factory
):
    """Attempting to forward to a conversation Bob is not a member of must return forbidden."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd3a@example.com", "fwd3b@example.com", "Alice", "Bob",
    )
    # Carol ↔ Alice (Bob is NOT in this conversation)
    carol = await register_user("fwd3c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd3c@example.com"}, headers=auth_headers(alice))
    alice_convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    target_conv_id = next(c["id"] for c in alice_convs if c["id"] != src_conv_id)

    orig_id = await _insert_message(session_factory, src_conv_id, alice_id, content="secret")

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                "to_conversation_id": target_conv_id,
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "forbidden"


# ---------------------------------------------------------------------------
# Test 4: Forward a message user CANNOT see (not in source conversation) → forbidden
# ---------------------------------------------------------------------------

async def test_forward_message_in_unseen_conversation_forbidden(
    client, register_user, auth_headers, session_factory
):
    """Bob cannot forward a message from a conversation he's not a member of."""
    # Alice ↔ Carol (Bob is NOT in this conversation)
    alice = await register_user("fwd4a@example.com", "Alice")
    carol = await register_user("fwd4c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd4c@example.com"}, headers=auth_headers(alice))
    alice_id = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    alice_convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    alice_carol_conv_id = alice_convs[0]["id"]

    # Bob ↔ Alice (Bob's own conversation, needed so Bob has somewhere to forward to)
    bob = await register_user("fwd4b@example.com", "Bob")
    await client.post("/contacts", json={"email": "fwd4b@example.com"}, headers=auth_headers(alice))
    bob_convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    bob_alice_conv_id = bob_convs[0]["id"]

    # Insert a message in the Alice↔Carol conversation (Bob can't see it)
    secret_msg_id = await _insert_message(
        session_factory, alice_carol_conv_id, alice_id, content="private"
    )

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "forward",
                "message_id": secret_msg_id,
                "to_conversation_id": bob_alice_conv_id,
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "forbidden"


# ---------------------------------------------------------------------------
# Test 5: Forward a soft-deleted message → forbidden
# ---------------------------------------------------------------------------

async def test_forward_deleted_message_forbidden(
    client, register_user, auth_headers, session_factory
):
    """Forwarding a soft-deleted message must return forbidden."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd5a@example.com", "fwd5b@example.com", "Alice", "Bob",
    )
    carol = await register_user("fwd5c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd5b@example.com"}, headers=auth_headers(carol))
    carol_convs = (await client.get("/conversations", headers=auth_headers(carol))).json()
    target_conv_id = carol_convs[0]["id"]

    # Insert a soft-deleted message
    del_id = await _insert_message(
        session_factory, src_conv_id, alice_id, content="deleted", deleted=True
    )

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "forward",
                "message_id": del_id,
                "to_conversation_id": target_conv_id,
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "forbidden"


# ---------------------------------------------------------------------------
# Test 6: Missing to_conversation_id → invalid_payload
# ---------------------------------------------------------------------------

async def test_forward_missing_to_conversation_id_invalid_payload(
    client, register_user, auth_headers, session_factory
):
    """Forward request without to_conversation_id must return invalid_payload."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd6a@example.com", "fwd6b@example.com", "Alice", "Bob",
    )
    orig_id = await _insert_message(session_factory, src_conv_id, alice_id, content="hi")

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            # Missing to_conversation_id
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                # to_conversation_id intentionally omitted
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_payload"


# ---------------------------------------------------------------------------
# Test 7: Malformed message_id UUID → invalid_payload
# ---------------------------------------------------------------------------

async def test_forward_malformed_message_id_invalid_payload(
    client, register_user, auth_headers, session_factory
):
    """Forward request with a non-UUID message_id must return invalid_payload."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd7a@example.com", "fwd7b@example.com", "Alice", "Bob",
    )

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({
                "type": "forward",
                "message_id": "not-a-uuid",
                "to_conversation_id": src_conv_id,
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_payload"
