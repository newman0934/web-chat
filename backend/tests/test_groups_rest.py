import pytest

pytestmark = pytest.mark.asyncio


async def _uid(client, headers):
    return (await client.get("/users/me", headers=headers)).json()["id"]


async def test_create_group_with_friends(client, register_user, auth_headers):
    alice = await register_user("ga@example.com", "Alice")
    await register_user("gb@example.com", "Bob")
    await register_user("gc@example.com", "Cara")
    # 先互加好友
    await client.post("/contacts", json={"email": "gb@example.com"}, headers=auth_headers(alice))
    await client.post("/contacts", json={"email": "gc@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    member_ids = [c["user_id"] for c in contacts]

    resp = await client.post(
        "/conversations/groups",
        json={"name": "三人組", "member_user_ids": member_ids},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["type"] == "group"
    assert data["name"] == "三人組"
    assert len(data["members"]) == 3  # alice + 2


async def test_create_group_rejects_non_friend(client, register_user, auth_headers):
    alice = await register_user("gx@example.com", "Alice")
    bob = await register_user("gy@example.com", "Bob")  # 沒加好友
    bob_id = await _uid(client, auth_headers(bob))
    resp = await client.post(
        "/conversations/groups",
        json={"name": "x", "member_user_ids": [bob_id]},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 400


async def test_create_group_empty_name_422(client, register_user, auth_headers):
    alice = await register_user("gz@example.com", "Alice")
    resp = await client.post(
        "/conversations/groups",
        json={"name": "", "member_user_ids": []},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 422
