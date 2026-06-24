"""多附件:WS 送訊綁定多個附件、數量/總量/歸屬驗證、去重、轉發、撤回(對應 BDD MA-01..07)。"""

import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Attachment

pytestmark = pytest.mark.asyncio


def _recv(ws):
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "presence":
            return msg


async def _direct(client, register_user, auth_headers):
    alice = await register_user("ma@example.com", "Alice")
    bob = await register_user("mb@example.com", "Bob")
    await client.post("/contacts", json={"email": "mb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    return alice, bob, conv["id"]


async def _upload(client, token, auth_headers, name="f.bin", data=b"x"):
    resp = await client.post(
        "/uploads",
        files={"file": (name, data, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── MA-01:多附件送出並依序顯示 ─────────────────────────────────────────
async def test_send_multiple_attachments_ordered(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    a1 = await _upload(client, alice, auth_headers, "1.bin")
    a2 = await _upload(client, alice, auth_headers, "2.bin")
    a3 = await _upload(client, alice, auth_headers, "3.bin")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": [a1, a2, a3], "temp_id": "t1",
            })
            ack = _recv(wa)
            assert ack["type"] == "ack"
            ids = [a["id"] for a in ack["message"]["attachments"]]
            assert ids == [a1, a2, a3]  # 順序與 attachment_ids 一致


# ── MA-02:超過 5 個被拒 ─────────────────────────────────────────────────
async def test_too_many_attachments(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    ids = [await _upload(client, alice, auth_headers, f"{i}.bin") for i in range(6)]
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": ids, "temp_id": "t",
            })
            assert _recv(wa)["reason"] == "too_many_attachments"


# ── MA-04:整則總量超過 10MB 被拒 ───────────────────────────────────────
async def test_attachments_too_large(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    # 直接種 5 個各 3MB 的(未綁定)附件(size 為中繼資料,不需真檔)→ 總 15MB > 10MB。
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    att_ids = []
    async with session_factory() as db:
        for i in range(5):
            a = Attachment(uploader_id=uuid.UUID(aid), stored_name=f"s{i}",
                           original_name=f"big{i}.bin", content_type="application/octet-stream",
                           size=3 * 1024 * 1024, is_image=False)
            db.add(a); await db.flush()
            att_ids.append(str(a.id))
        await db.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": att_ids, "temp_id": "t",
            })
            assert _recv(wa)["reason"] == "attachments_too_large"


# ── MA-07:非本人 / 已綁定附件被拒 ──────────────────────────────────────
async def test_foreign_attachment_rejected(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    mine = await _upload(client, alice, auth_headers, "mine.bin")
    bobs = await _upload(client, bob, auth_headers, "bobs.bin")  # 屬 Bob
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": [mine, bobs], "temp_id": "t",
            })
            assert _recv(wa)["reason"] == "invalid_attachment"


async def test_dedup_attachment_ids(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    a1 = await _upload(client, alice, auth_headers, "x.bin")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": [a1, a1], "temp_id": "t",  # 重複
            })
            ack = _recv(wa)
            assert len(ack["message"]["attachments"]) == 1  # 去重


async def test_attachments_only_no_content_ok(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    a1 = await _upload(client, alice, auth_headers, "only.bin")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": [a1], "temp_id": "t",
            })
            assert _recv(wa)["type"] == "ack"


# ── MA-05:轉發複製全部附件 ─────────────────────────────────────────────
async def test_forward_copies_all_attachments(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    # 第二個對話(Alice↔Carol)當轉發目標
    carol = await register_user("mc@example.com", "Carol")
    await client.post("/contacts", json={"email": "mc@example.com"}, headers=auth_headers(alice))
    convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    to_conv = next(c["id"] for c in convs if c["id"] != conv_id)
    a1 = await _upload(client, alice, auth_headers, "f1.bin")
    a2 = await _upload(client, alice, auth_headers, "f2.bin")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "src",
                "attachment_ids": [a1, a2], "temp_id": "t",
            })
            src = _recv(wa)["message"]
            wa.send_json({"type": "forward", "message_id": src["id"], "to_conversation_id": to_conv})
            fwd = _recv(wa)["message"]
            assert len(fwd["attachments"]) == 2


# ── MA-06:撤回清空附件 ─────────────────────────────────────────────────
async def test_recall_clears_attachments(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    a1 = await _upload(client, alice, auth_headers, "r1.bin")
    a2 = await _upload(client, alice, auth_headers, "r2.bin")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id, "content": "",
                "attachment_ids": [a1, a2], "temp_id": "t",
            })
            mid = _recv(wa)["message"]["id"]
            wa.send_json({"type": "recall", "message_id": mid})
            evt = _recv(wa)
            assert evt["type"] == "message_updated"
            assert evt["message"]["attachments"] == []
