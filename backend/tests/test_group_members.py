import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _make_group(client, register_user, auth_headers):
    alice = await register_user("gma@example.com", "Alice")
    bob = await register_user("gmb@example.com", "Bob")
    await client.post("/contacts", json={"email": "gmb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]},
            headers=auth_headers(alice))).json()
    return alice, bob, aid, bid, conv["id"]


async def test_admin_adds_member_by_email_nonfriend(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    # carol 非 alice 好友
    await register_user("gmc@example.com", "Carol")
    resp = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "gmc@example.com"}, headers=auth_headers(alice))
    assert resp.status_code == 200, resp.text
    cid = (await client.get("/users/me", headers=auth_headers(await register_user("gmc2@example.com", "X")))).json()  # noqa: not used
    body = resp.json()
    emails = {m["email"] for m in body["members"]}
    assert "gmc@example.com" in emails
    # 系統訊息落庫
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert any(m["kind"] == "system" and "加入群組" in m["content"] for m in msgs)


async def test_add_member_by_user_id(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    carol = await register_user("gmc3@example.com", "Carol")
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    resp = await client.post(f"/conversations/{conv_id}/members",
            json={"user_id": cid}, headers=auth_headers(alice))
    assert resp.status_code == 200
    assert resp.json()["roles"][cid] == "member"


async def test_add_member_errors(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    # 非 admin（bob）加人 → 403
    r1 = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "gmb@example.com"}, headers=auth_headers(bob))
    assert r1.status_code == 403
    # 已是成員 → 400
    r2 = await client.post(f"/conversations/{conv_id}/members",
            json={"user_id": bid}, headers=auth_headers(alice))
    assert r2.status_code == 400
    # 查無 email → 404
    r3 = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "nobody@example.com"}, headers=auth_headers(alice))
    assert r3.status_code == 404


async def test_admin_removes_member(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    resp = await client.request("DELETE", f"/conversations/{conv_id}/members/{bid}",
            headers=auth_headers(alice))
    assert resp.status_code == 200
    assert bid not in resp.json()["roles"]
    # 不能移自己
    r2 = await client.request("DELETE", f"/conversations/{conv_id}/members/{aid}",
            headers=auth_headers(alice))
    assert r2.status_code == 400


async def test_add_member_broadcasts_ws(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    carol = await register_user("gmd@example.com", "Carol")
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as ws_bob:
            await client.post(f"/conversations/{conv_id}/members",
                    json={"user_id": cid}, headers=auth_headers(alice))
            seen = {ws_bob.receive_json()["type"] for _ in range(2)}
            assert "message" in seen and "conversation_updated" in seen
