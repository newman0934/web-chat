import pytest

pytestmark = pytest.mark.asyncio


async def test_add_contact_creates_bidirectional_and_conversation(
    client, register_user, auth_headers
):
    alice = await register_user("alice@example.com", "Alice")
    await register_user("bob@example.com", "Bob")

    resp = await client.post(
        "/contacts", json={"email": "bob@example.com"}, headers=auth_headers(alice)
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "bob@example.com"
    assert "conversation_id" in data

    # Alice 的好友清單含 Bob
    alice_contacts = await client.get("/contacts", headers=auth_headers(alice))
    assert [c["email"] for c in alice_contacts.json()] == ["bob@example.com"]


async def test_add_nonexistent_email_404(client, register_user, auth_headers):
    alice = await register_user("a2@example.com", "Alice")
    resp = await client.post(
        "/contacts", json={"email": "ghost@example.com"}, headers=auth_headers(alice)
    )
    assert resp.status_code == 404


async def test_add_duplicate_contact_409(client, register_user, auth_headers):
    alice = await register_user("a3@example.com", "Alice")
    await register_user("b3@example.com", "Bob")
    body = {"email": "b3@example.com"}
    assert (
        await client.post("/contacts", json=body, headers=auth_headers(alice))
    ).status_code == 201
    resp = await client.post("/contacts", json=body, headers=auth_headers(alice))
    assert resp.status_code == 409


async def test_cannot_add_self(client, register_user, auth_headers):
    alice = await register_user("self@example.com", "Alice")
    resp = await client.post(
        "/contacts", json={"email": "self@example.com"}, headers=auth_headers(alice)
    )
    assert resp.status_code == 400
