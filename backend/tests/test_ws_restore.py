import uuid
from datetime import datetime, timedelta, timezone

import pytest
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



async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("rsa@example.com", "Alice")
    bob = await register_user("rsb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rsb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="secret")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_delete_keeps_db_content_masks_output(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            evt = _recv(wa)
            assert evt["message"]["content"] == ""           # 輸出遮蔽
            assert evt["message"]["deleted"] is True
            assert evt["message"]["deleted_at"] is not None
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        assert m.content == "secret"                          # DB 仍保留原文


async def test_restore_within_window(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            _recv(wa); _recv(wb)
            wa.send_json({"type": "restore", "message_id": mid})
            ea = _recv(wa); eb = _recv(wb)
            for evt in (ea, eb):
                assert evt["type"] == "message_updated"
                assert evt["message"]["deleted"] is False
                assert evt["message"]["content"] == "secret"
                assert evt["message"]["deleted_at"] is None


async def test_restore_non_sender_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            _recv(wa); _recv(wb)
            wb.send_json({"type": "restore", "message_id": mid})
            evt = _recv(wb)
            assert evt["type"] == "error" and evt["reason"] == "forbidden"


async def test_restore_past_window_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            _recv(wa)
    # 把 deleted_at 推到 6 分鐘前 → 超過 5 分鐘還原窗
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.deleted_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        await s.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "restore", "message_id": mid})
            evt = _recv(wa)
            assert evt["type"] == "error" and evt["reason"] == "restore_window_passed"


async def test_restore_non_deleted_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "restore", "message_id": mid})
            evt = _recv(wa)
            assert evt["type"] == "error" and evt["reason"] == "forbidden"


async def test_conversation_list_masks_deleted_last_message(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    # alice deletes her (only / last) message via WS
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            _recv(wa)
    # GET /conversations must NOT expose the original content in last_message
    convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    target = next(c for c in convs if c["id"] == conv_id)
    assert target["last_message"]["deleted"] is True
    assert target["last_message"]["content"] == ""
