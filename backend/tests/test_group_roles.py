import pytest

pytestmark = pytest.mark.asyncio


async def _make_group(client, register_user, auth_headers):
    alice = await register_user("gra@example.com", "Alice")
    bob = await register_user("grb@example.com", "Bob")
    await client.post("/contacts", json={"email": "grb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]},
            headers=auth_headers(alice))).json()
    return alice, bob, aid, bid, conv


async def test_conversation_lists_roles_creator_admin(client, register_user, auth_headers):
    alice, bob, aid, bid, conv = await _make_group(client, register_user, auth_headers)
    assert conv["roles"][aid] == "admin"
    assert conv["roles"][bid] == "member"
    convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    g = next(c for c in convs if c["id"] == conv["id"])
    assert g["roles"][aid] == "admin" and g["roles"][bid] == "member"
