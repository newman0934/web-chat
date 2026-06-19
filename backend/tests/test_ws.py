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

            pushed = ws_bob.receive_json()
            assert pushed["type"] == "message"
            assert pushed["message"]["content"] == "hello bob"

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
