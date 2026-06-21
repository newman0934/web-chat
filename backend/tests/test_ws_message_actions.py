import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("wa@example.com", "Alice")
    bob = await register_user("wb@example.com", "Bob")
    await client.post("/contacts", json={"email": "wb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="orig")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edit_broadcasts_updated(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb, tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "edited!"})
            evt_a = wa.receive_json()
            evt_b = wb.receive_json()
            for evt in (evt_a, evt_b):
                assert evt["type"] == "message_updated"
                assert evt["message"]["content"] == "edited!"
                assert evt["message"]["edited_at"] is not None


async def test_edit_non_sender_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "edit", "message_id": mid, "content": "hack"})
            assert wb.receive_json()["reason"] == "forbidden"


async def test_delete_soft_masks_content(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            evt = wa.receive_json()
            assert evt["message"]["deleted"] is True
            assert evt["message"]["content"] == ""


async def test_react_toggle(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "👍"})
            on = wb.receive_json()
            grp = on["message"]["reactions"][0]
            assert grp["emoji"] == "👍" and grp["count"] == 1 and bid in grp["user_ids"]
            wb.send_json({"type": "react", "message_id": mid, "emoji": "👍"})
            off = wb.receive_json()
            assert off["message"]["reactions"] == []


async def test_react_invalid_emoji(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "lol"})
            assert wb.receive_json()["reason"] == "invalid_reaction"


async def test_react_on_deleted_message_forbidden(client, register_user, auth_headers, session_factory):
    """React on a deleted message must return forbidden, even with a valid emoji."""
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        # Step 1: alice deletes her message; bob's socket is open so it also receives the broadcast.
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            # alice receives message_updated (broadcast to actor)
            delete_evt_a = wa.receive_json()
            assert delete_evt_a["type"] == "message_updated"
            assert delete_evt_a["message"]["deleted"] is True
            # bob also receives the delete broadcast — drain it before we react
            delete_evt_b = wb.receive_json()
            assert delete_evt_b["type"] == "message_updated"

            # Step 2: bob tries to react on the now-deleted message
            wb.send_json({"type": "react", "message_id": mid, "emoji": "👍"})
            err = wb.receive_json()
            assert err["type"] == "error"
            assert err["reason"] == "forbidden"


async def test_edit_deleted_message_forbidden(client, register_user, auth_headers, session_factory):
    """Editing a deleted message must return forbidden."""
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            # alice deletes her message
            wa.send_json({"type": "delete", "message_id": mid})
            delete_evt = wa.receive_json()
            assert delete_evt["type"] == "message_updated"
            assert delete_evt["message"]["deleted"] is True

            # alice tries to edit the already-deleted message
            wa.send_json({"type": "edit", "message_id": mid, "content": "x"})
            err = wa.receive_json()
            assert err["type"] == "error"
            assert err["reason"] == "forbidden"


async def test_delete_broadcasts_to_partner(client, register_user, auth_headers, session_factory):
    """Deleting a message must broadcast message_updated with deleted=True to BOTH alice and bob."""
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            evt_a = wa.receive_json()
            evt_b = wb.receive_json()
            for evt in (evt_a, evt_b):
                assert evt["type"] == "message_updated"
                assert evt["message"]["deleted"] is True
