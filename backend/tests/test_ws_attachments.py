import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _direct(client, register_user, auth_headers):
    alice = await register_user("aa@example.com", "Alice")
    bob = await register_user("ab@example.com", "Bob")
    await client.post("/contacts", json={"email": "ab@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    return alice, bob, conv["id"]


async def test_ws_message_with_attachment(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    att = (await client.post(
        "/uploads",
        files={"file": ("p.png", b"\x89PNG", "image/png")},
        headers=auth_headers(alice),
    )).json()

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "", "attachment_ids": [att["id"]], "temp_id": "t1",
            })
            ack = wa.receive_json()
            assert ack["type"] == "ack"
            assert ack["message"]["attachments"][0]["id"] == att["id"]
            assert ack["message"]["attachments"][0]["is_image"] is True

    # 歷史也帶 attachment
    history = await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(bob))
    assert history.json()[0]["attachments"][0]["original_name"] == "p.png"


async def test_ws_rejects_used_or_foreign_attachment(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    # Bob 的附件，Alice 不能用
    bob_att = (await client.post(
        "/uploads",
        files={"file": ("x.txt", b"x", "text/plain")},
        headers=auth_headers(bob),
    )).json()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "hi", "attachment_ids": [bob_att["id"]], "temp_id": "t",
            })
            assert wa.receive_json()["reason"] == "invalid_attachment"


async def test_ws_rejects_already_used_attachment(client, register_user, auth_headers):
    alice, _bob, conv_id = await _direct(client, register_user, auth_headers)
    att = (await client.post(
        "/uploads",
        files={"file": ("r.png", b"\x89PNG", "image/png")},
        headers=auth_headers(alice),
    )).json()

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            # 第一次送出 — 應該成功，attachment 被綁定到 message
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "", "attachment_ids": [att["id"]], "temp_id": "t1",
            })
            ack = wa.receive_json()
            assert ack["type"] == "ack"

            # 第二次送出同一個 attachment_id — 已被綁定，應回 invalid_attachment
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "", "attachment_ids": [att["id"]], "temp_id": "t2",
            })
            err = wa.receive_json()
            assert err["type"] == "error"
            assert err["reason"] == "invalid_attachment"


async def test_ws_empty_content_no_attachment_invalid(client, register_user, auth_headers):
    alice, _bob, conv_id = await _direct(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "message", "conversation_id": conv_id, "content": "", "temp_id": "t"})
            assert wa.receive_json()["reason"] == "invalid_payload"
