import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory, content="v1"):
    alice = await register_user("mra@example.com", "Alice")
    bob = await register_user("mrb@example.com", "Bob")
    await client.post("/contacts", json={"email": "mrb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content=content)
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edits_returns_versions_in_order(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            wa.receive_json()
            wa.send_json({"type": "edit", "message_id": mid, "content": "v3"})
            wa.receive_json()
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 200, resp.text
    contents = [v["content"] for v in resp.json()]
    assert contents == ["v1", "v2", "v3"]  # 舊版 v1、v2 + 目前 v3


async def test_edits_unedited_returns_current_only(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="only")
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 200
    assert [v["content"] for v in resp.json()] == ["only"]


async def test_edits_non_member_404(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    carol = await register_user("mrc@example.com", "Carol")
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(carol))
    assert resp.status_code == 404


async def test_edits_deleted_message_403(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            wa.receive_json()
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 403
