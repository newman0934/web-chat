import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.message_policy import is_valid_reaction_emoji
from app.models import Message

pytestmark = pytest.mark.asyncio


def test_is_valid_reaction_emoji_unit():
    assert is_valid_reaction_emoji("🎉") is True
    assert is_valid_reaction_emoji("👍") is True
    assert is_valid_reaction_emoji("hello") is False     # ASCII 文字
    assert is_valid_reaction_emoji("a") is False
    assert is_valid_reaction_emoji("") is False
    assert is_valid_reaction_emoji("   ") is False
    assert is_valid_reaction_emoji("🎉🎉🎉🎉🎉🎉🎉🎉🎉") is False  # 9 codepoints > 8
    assert is_valid_reaction_emoji(None) is False


async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("rva@example.com", "Alice")
    bob = await register_user("rvb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rvb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="hi")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_react_arbitrary_emoji_accepted(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "🎉"})
            evt = wb.receive_json()
            assert evt["type"] == "message_updated"
            assert evt["message"]["reactions"][0]["emoji"] == "🎉"


async def test_react_text_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "lol"})
            assert wb.receive_json()["reason"] == "invalid_reaction"
