import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.main import app
from app.models import Message, MessageEdit

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory, content="orig"):
    alice = await register_user("eha@example.com", "Alice")
    bob = await register_user("ehb@example.com", "Bob")
    await client.post("/contacts", json={"email": "ehb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content=content)
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edit_snapshots_previous_version(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            evt = wa.receive_json()
            assert evt["message"]["content"] == "v2"
    async with session_factory() as s:
        rows = (await s.execute(
            select(MessageEdit).where(MessageEdit.message_id == uuid.UUID(mid))
        )).scalars().all()
        assert [e.content for e in rows] == ["v1"]


async def test_two_edits_build_version_chain(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            wa.receive_json()
            wa.send_json({"type": "edit", "message_id": mid, "content": "v3"})
            wa.receive_json()
    async with session_factory() as s:
        rows = (await s.execute(
            select(MessageEdit).where(MessageEdit.message_id == uuid.UUID(mid))
            .order_by(MessageEdit.created_at)
        )).scalars().all()
        assert [e.content for e in rows] == ["v1", "v2"]


async def test_edit_past_window_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    # 把 created_at 推到 16 分鐘前 → 超過 15 分鐘編輯窗
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        await s.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "late"})
            evt = wa.receive_json()
            assert evt["type"] == "error"
            assert evt["reason"] == "edit_window_passed"
