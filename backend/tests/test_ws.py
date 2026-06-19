import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

pytestmark = pytest.mark.asyncio


async def _setup(client, register_user, auth_headers):
    alice = await register_user("wsa@example.com", "Alice")
    bob = await register_user("wsb@example.com", "Bob")
    resp = await client.post(
        "/contacts", json={"email": "wsb@example.com"}, headers=auth_headers(alice)
    )
    conv_id = resp.json()["conversation_id"]
    return alice, bob, conv_id


async def test_ws_rejects_invalid_token(session_factory):
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect):
            with tc.websocket_connect("/ws?token=not-a-jwt") as ws:
                ws.receive_json()


async def test_ws_message_ack_and_push_and_persist(
    client, register_user, auth_headers
):
    alice, bob, conv_id = await _setup(client, register_user, auth_headers)

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as ws_bob, tc.websocket_connect(
            f"/ws?token={alice}"
        ) as ws_alice:
            ws_alice.send_json(
                {
                    "type": "message",
                    "conversation_id": conv_id,
                    "content": "hello bob",
                    "temp_id": "tmp-1",
                }
            )
            ack = ws_alice.receive_json()
            assert ack["type"] == "ack"
            assert ack["temp_id"] == "tmp-1"
            assert ack["message"]["content"] == "hello bob"
            assert ack["message"]["read_count"] == 0

            pushed = ws_bob.receive_json()
            assert pushed["type"] == "message"
            assert pushed["message"]["content"] == "hello bob"
            assert pushed["message"]["read_count"] == 0

    # 落庫驗證：透過 REST 撈歷史
    history = await client.get(
        f"/conversations/{conv_id}/messages", headers=auth_headers(bob)
    )
    assert [m["content"] for m in history.json()] == ["hello bob"]


async def test_ws_send_to_foreign_conversation_errors(
    client, register_user, auth_headers
):
    alice, bob, conv_id = await _setup(client, register_user, auth_headers)
    outsider = await register_user("wsout@example.com", "Out")

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={outsider}") as ws:
            ws.send_json(
                {"type": "message", "conversation_id": conv_id, "content": "x",
                 "temp_id": "t"}
            )
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["reason"] == "forbidden"


async def test_ws_group_broadcast_to_all_members(client, register_user, auth_headers):
    alice = await register_user("wga@example.com", "Alice")
    bob = await register_user("wgb@example.com", "Bob")
    cara = await register_user("wgc@example.com", "Cara")
    await client.post("/contacts", json={"email": "wgb@example.com"}, headers=auth_headers(alice))
    await client.post("/contacts", json={"email": "wgc@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    member_ids = [c["user_id"] for c in contacts]
    conv = (await client.post(
        "/conversations/groups",
        json={"name": "G", "member_user_ids": member_ids},
        headers=auth_headers(alice),
    )).json()
    conv_id = conv["id"]

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb, \
             tc.websocket_connect(f"/ws?token={cara}") as wc, \
             tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "message", "conversation_id": conv_id,
                          "content": "hi all", "temp_id": "t1"})
            assert wa.receive_json()["type"] == "ack"
            assert wb.receive_json()["message"]["content"] == "hi all"
            assert wc.receive_json()["message"]["content"] == "hi all"


async def test_ws_group_read_broadcasts_message_ids(client, register_user, auth_headers):
    alice = await register_user("wra@example.com", "Alice")
    bob = await register_user("wrb@example.com", "Bob")
    await client.post("/contacts", json={"email": "wrb@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    conv = (await client.post(
        "/conversations/groups",
        json={"name": "G2", "member_user_ids": [contacts[0]["user_id"]]},
        headers=auth_headers(alice),
    )).json()
    conv_id = conv["id"]

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "message", "conversation_id": conv_id,
                          "content": "ping", "temp_id": "t"})
            wa.receive_json()  # ack
            wb.receive_json()  # message push
            wb.send_json({"type": "read", "conversation_id": conv_id})
            evt = wa.receive_json()
            assert evt["type"] == "read"
            assert evt["reader_id"]
            assert len(evt["message_ids"]) == 1
