import pytest

pytestmark = pytest.mark.asyncio


async def _trio_group(client, register_user, auth_headers):
    alice = await register_user("aoa@example.com", "Alice")
    bob = await register_user("aob@example.com", "Bob")
    carol = await register_user("aoc@example.com", "Carol")
    for em in ("aob@example.com", "aoc@example.com"):
        await client.post("/contacts", json={"email": em}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid, cid]},
            headers=auth_headers(alice))).json()
    return (alice, bob, carol), (aid, bid, cid), conv["id"]


async def test_rename_group(client, register_user, auth_headers):
    (alice, *_), _, conv_id = await _trio_group(client, register_user, auth_headers)
    resp = await client.patch(f"/conversations/{conv_id}", json={"name": "新名字"},
            headers=auth_headers(alice))
    assert resp.status_code == 200 and resp.json()["name"] == "新名字"
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert any(m["kind"] == "system" and "改名為" in m["content"] for m in msgs)


async def test_promote_and_demote(client, register_user, auth_headers):
    (alice, bob, carol), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    up = await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "admin"}, headers=auth_headers(alice))
    assert up.status_code == 200 and up.json()["roles"][bid] == "admin"
    down = await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "member"}, headers=auth_headers(alice))
    assert down.json()["roles"][bid] == "member"


async def test_cannot_demote_last_admin(client, register_user, auth_headers):
    (alice, *_), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    resp = await client.patch(f"/conversations/{conv_id}/members/{aid}/role",
            json={"role": "member"}, headers=auth_headers(alice))
    assert resp.status_code == 400


async def test_leave_blocks_last_admin_then_succeeds_after_promote(client, register_user, auth_headers):
    (alice, bob, carol), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    blocked = await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    assert blocked.status_code == 400
    await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "admin"}, headers=auth_headers(alice))
    ok = await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    assert ok.status_code == 200
    # alice 已非成員
    convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    assert all(c["id"] != conv_id for c in convs)


async def test_last_member_leave_deletes_group(client, register_user, auth_headers):
    alice = await register_user("aolone@example.com", "Alice")
    bob = await register_user("aolone2@example.com", "Bob")
    await client.post("/contacts", json={"email": "aolone2@example.com"}, headers=auth_headers(alice))
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]}, headers=auth_headers(alice))).json()
    conv_id = conv["id"]
    # bob 退出（alice 是唯一 admin，bob 是 member）
    await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(bob))
    # alice 此時是最後一人，退出 → 刪群
    await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    # 對話應已不存在
    msgs = await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))
    assert msgs.status_code == 404
