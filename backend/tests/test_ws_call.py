import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _setup(client, register_user, auth_headers):
    alice = await register_user("vva@example.com", "Alice")
    bob = await register_user("vvb@example.com", "Bob")
    await client.post("/contacts", json={"email": "vvb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    return alice, bob, aid, bid


async def test_call_offer_relayed_to_online_friend(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as ws_bob, \
             tc.websocket_connect(f"/ws?token={alice}") as ws_alice:
            ws_alice.send_json({
                "type": "call_offer", "to_user_id": bid,
                "sdp": {"type": "offer", "sdp": "v=0..."},
            })
            got = ws_bob.receive_json()
            assert got["type"] == "call_offer"
            assert got["from"]["id"] == aid
            assert got["from"]["display_name"] == "Alice"
            assert got["sdp"] == {"type": "offer", "sdp": "v=0..."}


async def test_call_answer_relayed(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as ws_alice, \
             tc.websocket_connect(f"/ws?token={bob}") as ws_bob:
            ws_bob.send_json({
                "type": "call_answer", "to_user_id": aid,
                "sdp": {"type": "answer", "sdp": "v=0..."},
            })
            got = ws_alice.receive_json()
            assert got["type"] == "call_answer"
            assert got["from"]["id"] == bid


async def test_call_signal_rejected_for_non_friend(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    outsider = await register_user("vvout@example.com", "Out")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={outsider}") as ws:
            ws.send_json({"type": "call_offer", "to_user_id": bid, "sdp": {"type": "offer", "sdp": "x"}})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["reason"] == "forbidden"


async def test_call_offer_to_offline_friend_returns_unavailable(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as ws_alice:
            ws_alice.send_json({"type": "call_offer", "to_user_id": bid, "sdp": {"type": "offer", "sdp": "x"}})
            resp = ws_alice.receive_json()
            assert resp["type"] == "call_unavailable"
            assert resp["to_user_id"] == bid
