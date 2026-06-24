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
# 共用 helper
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
# 測試 1:轉發文字訊息 → 產生新訊息、帶 forwarded_from、廣播給雙方
# ---------------------------------------------------------------------------

async def test_forward_text_broadcasts_to_target_members(
    client, register_user, auth_headers, session_factory
):
    """Forward a text message: target conversation gets a new message with
    forwarded_from = original author; both forwarder AND another target member
    receive the broadcast."""
    # Alice ↔ Bob(來源對話)
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd1a@example.com", "fwd1b@example.com", "Alice", "Bob",
    )
    # Carol ↔ Bob(目標對話 —— Bob 會轉發給 Carol)
    carol = await register_user("fwd1c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd1b@example.com"}, headers=auth_headers(carol))
    target_convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    target_conv_id = next(c["id"] for c in target_convs if c["id"] != src_conv_id)
    carol_id = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]

    # Alice 在 src_conv 貼出原始訊息
    orig_id = await _insert_message(session_factory, src_conv_id, alice_id, content="hello world")

    with TestClient(app) as tc:
        with (
            tc.websocket_connect(f"/ws?token={bob}") as wb,
            tc.websocket_connect(f"/ws?token={carol}") as wc,
        ):
            # Bob 把 Alice 的訊息轉發到 Bob↔Carol 對話
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                "to_conversation_id": target_conv_id,
            })

            # Bob(轉發者)與 Carol(目標成員)都應收到廣播
            evt_b = _recv(wb)
            evt_c = _recv(wc)

    for evt in (evt_b, evt_c):
        assert evt["type"] == "message"
        msg = evt["message"]
        assert msg["conversation_id"] == target_conv_id
        assert msg["content"] == "hello world"
        # forwarded_from 應指向 Alice(原寄件人)
        assert msg["forwarded_from"] is not None
        assert msg["forwarded_from"]["id"] == alice_id
        assert msg["forwarded_from"]["display_name"] == "Alice"
        # 新訊息的寄件人是 Bob
        assert msg["sender_id"] == bob_id
        # 不繼承 reply_to
        assert msg["reply_to"] is None


# ---------------------------------------------------------------------------
# 測試 2:轉發含附件訊息 → 產生新 Attachment 列、共用 stored_name
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

    # 插入帶附件的原始訊息
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

    # 驗證序列化 payload 內的 attachment(不外露 stored_name;改驗 is_image)
    assert len(msg["attachments"]) == 1
    assert msg["attachments"][0]["is_image"] is True
    assert msg["attachments"][0]["original_name"] == "photo.png"

    # 驗證 DB 有一列新的 Attachment 綁到新訊息
    async with session_factory() as s:
        result = await s.execute(
            select(Attachment).where(Attachment.message_id == new_msg_id)
        )
        new_att = result.scalar_one_or_none()
    assert new_att is not None
    assert new_att.stored_name == stored_name
    assert new_att.original_name == "photo.png"
    assert new_att.is_image is True
    # 不應與原附件是同一列
    orig_att_result = None
    async with session_factory() as s:
        result = await s.execute(
            select(Attachment).where(Attachment.message_id == uuid.UUID(orig_id))
        )
        orig_att_result = result.scalar_one_or_none()
    assert orig_att_result is not None
    assert new_att.id != orig_att_result.id  # different rows


# ---------------------------------------------------------------------------
# 測試 3:轉發到使用者「非成員」的對話 → forbidden
# ---------------------------------------------------------------------------

async def test_forward_to_non_member_conversation_forbidden(
    client, register_user, auth_headers, session_factory
):
    """Attempting to forward to a conversation Bob is not a member of must return forbidden."""
    alice, bob, src_conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers,
        "fwd3a@example.com", "fwd3b@example.com", "Alice", "Bob",
    )
    # Carol ↔ Alice(Bob 不在此對話)
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
# 測試 4:轉發使用者「看不到」的訊息(不在來源對話)→ forbidden
# ---------------------------------------------------------------------------

async def test_forward_message_in_unseen_conversation_forbidden(
    client, register_user, auth_headers, session_factory
):
    """Bob cannot forward a message from a conversation he's not a member of."""
    # Alice ↔ Carol(Bob 不在此對話)
    alice = await register_user("fwd4a@example.com", "Alice")
    carol = await register_user("fwd4c@example.com", "Carol")
    await client.post("/contacts", json={"email": "fwd4c@example.com"}, headers=auth_headers(alice))
    alice_id = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    alice_convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    alice_carol_conv_id = alice_convs[0]["id"]

    # Bob ↔ Alice(Bob 自己的對話,讓 Bob 有可轉發的去處)
    bob = await register_user("fwd4b@example.com", "Bob")
    await client.post("/contacts", json={"email": "fwd4b@example.com"}, headers=auth_headers(alice))
    bob_convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    bob_alice_conv_id = bob_convs[0]["id"]

    # 在 Alice↔Carol 對話插入一則訊息(Bob 看不到)
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
# 測試 5:轉發已軟刪的訊息 → forbidden
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

    # 插入一則已軟刪的訊息
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
# 測試 6:缺 to_conversation_id → invalid_payload
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
            # 缺 to_conversation_id
            wb.send_json({
                "type": "forward",
                "message_id": orig_id,
                # 故意省略 to_conversation_id
            })
            err = _recv(wb)

    assert err["type"] == "error"
    assert err["reason"] == "invalid_payload"


# ---------------------------------------------------------------------------
# 測試 7:message_id UUID 格式錯誤 → invalid_payload
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
