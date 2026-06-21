"""序列化 reply_to / forwarded_from 的 REST 歷史 API 測試。

覆蓋：
  - 帶 reply_to_message_id 的訊息 → history 回傳 reply_to 物件
  - 被引用訊息已軟刪 → reply_to.deleted=true, content=""
  - 帶 forwarded_from_user_id 的訊息 → history 回傳 forwarded_from 物件
  - 普通訊息 → reply_to=null, forwarded_from=null
  - 被引用訊息有 attachment → has_attachment=true
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models import Attachment, Conversation, ConversationMember, Message, User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 共用 helper
# ---------------------------------------------------------------------------

async def _setup_pair(client, register_user, auth_headers, session_factory):
    """建立兩個使用者並讓他們成為好友（產生 direct conversation）。
    回傳 (alice_token, bob_token, conv_id, alice_id, bob_id)。
    """
    alice = await register_user("rfsa@example.com", "Alice")
    bob = await register_user("rfsb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rfsb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    alice_id = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bob_id = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    return alice, bob, conv["id"], alice_id, bob_id


async def _get_history(client, auth_headers, token, conv_id) -> list[dict]:
    resp = await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_reply_to_present_in_history(client, register_user, auth_headers, session_factory):
    """帶 reply_to_message_id 的訊息，歷史 API 應回傳 reply_to 物件。"""
    alice, bob, conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    async with session_factory() as s:
        original = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(alice_id),
            content="original message",
        )
        s.add(original)
        await s.flush()
        reply = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(bob_id),
            content="reply message",
            reply_to_message_id=original.id,
        )
        s.add(reply)
        await s.commit()
        orig_id = str(original.id)
        reply_id = str(reply.id)

    msgs = await _get_history(client, auth_headers, alice, conv_id)
    reply_out = next(m for m in msgs if m["id"] == reply_id)

    assert reply_out["reply_to"] is not None
    rt = reply_out["reply_to"]
    assert rt["id"] == orig_id
    assert rt["sender_id"] == alice_id
    assert rt["content"] == "original message"
    assert rt["deleted"] is False
    assert rt["has_attachment"] is False
    # 普通訊息自身的 forwarded_from 應為 null
    assert reply_out["forwarded_from"] is None


async def test_reply_to_soft_deleted_original(client, register_user, auth_headers, session_factory):
    """被引用訊息已軟刪 → reply_to.deleted=true, content="" 。"""
    alice, bob, conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    async with session_factory() as s:
        original = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(alice_id),
            content="will be deleted",
            deleted_at=datetime.now(timezone.utc),  # 已軟刪
        )
        s.add(original)
        await s.flush()
        reply = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(bob_id),
            content="reply to deleted",
            reply_to_message_id=original.id,
        )
        s.add(reply)
        await s.commit()
        reply_id = str(reply.id)

    msgs = await _get_history(client, auth_headers, alice, conv_id)
    reply_out = next(m for m in msgs if m["id"] == reply_id)

    assert reply_out["reply_to"] is not None
    rt = reply_out["reply_to"]
    assert rt["deleted"] is True
    assert rt["content"] == ""
    assert rt["has_attachment"] is False  # 刪除後不查 attachment


async def test_forwarded_from_present_in_history(client, register_user, auth_headers, session_factory):
    """帶 forwarded_from_user_id 的訊息，歷史 API 應回傳 forwarded_from 物件。"""
    alice, bob, conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    async with session_factory() as s:
        fwd = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(alice_id),
            content="forwarded content",
            forwarded_from_user_id=uuid.UUID(bob_id),
        )
        s.add(fwd)
        await s.commit()
        fwd_id = str(fwd.id)

    msgs = await _get_history(client, auth_headers, alice, conv_id)
    fwd_out = next(m for m in msgs if m["id"] == fwd_id)

    assert fwd_out["forwarded_from"] is not None
    ff = fwd_out["forwarded_from"]
    assert ff["id"] == bob_id
    assert ff["display_name"] == "Bob"
    # 轉發訊息自身的 reply_to 應為 null
    assert fwd_out["reply_to"] is None


async def test_plain_message_both_null(client, register_user, auth_headers, session_factory):
    """普通訊息 → reply_to=null, forwarded_from=null。"""
    alice, bob, conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    async with session_factory() as s:
        plain = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(alice_id),
            content="just a normal message",
        )
        s.add(plain)
        await s.commit()
        plain_id = str(plain.id)

    msgs = await _get_history(client, auth_headers, alice, conv_id)
    plain_out = next(m for m in msgs if m["id"] == plain_id)

    assert plain_out["reply_to"] is None
    assert plain_out["forwarded_from"] is None


async def test_reply_to_has_attachment_true(client, register_user, auth_headers, session_factory):
    """被引用訊息有 attachment → reply_to.has_attachment=true。"""
    alice, bob, conv_id, alice_id, bob_id = await _setup_pair(
        client, register_user, auth_headers, session_factory
    )
    async with session_factory() as s:
        original = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(alice_id),
            content="message with attachment",
        )
        s.add(original)
        await s.flush()
        att = Attachment(
            message_id=original.id,
            uploader_id=uuid.UUID(alice_id),
            original_name="file.txt",
            stored_name="stored_file.txt",
            content_type="text/plain",
            size=100,
            is_image=False,
        )
        s.add(att)
        reply = Message(
            conversation_id=uuid.UUID(conv_id),
            sender_id=uuid.UUID(bob_id),
            content="reply to message with attachment",
            reply_to_message_id=original.id,
        )
        s.add(reply)
        await s.commit()
        reply_id = str(reply.id)

    msgs = await _get_history(client, auth_headers, alice, conv_id)
    reply_out = next(m for m in msgs if m["id"] == reply_id)

    assert reply_out["reply_to"] is not None
    rt = reply_out["reply_to"]
    assert rt["has_attachment"] is True
    assert rt["deleted"] is False
