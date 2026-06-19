import pytest

pytestmark = pytest.mark.asyncio


async def test_register_returns_token(client):
    resp = await client.post(
        "/auth/register",
        json={"email": "a@example.com", "display_name": "Alice", "password": "secret123"},
    )
    assert resp.status_code == 201
    assert "access_token" in resp.json()


async def test_register_duplicate_email_conflicts(client):
    body = {"email": "dup@example.com", "display_name": "Dup", "password": "secret123"}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    resp = await client.post("/auth/register", json=body)
    assert resp.status_code == 409


async def test_login_success_and_wrong_password(client, register_user):
    await register_user("b@example.com", "Bob")
    ok = await client.post(
        "/auth/login", json={"email": "b@example.com", "password": "secret123"}
    )
    assert ok.status_code == 200
    bad = await client.post(
        "/auth/login", json={"email": "b@example.com", "password": "nope"}
    )
    assert bad.status_code == 401


async def test_users_me_requires_token(client, register_user, auth_headers):
    token = await register_user("c@example.com", "Carol")
    unauth = await client.get("/users/me")
    assert unauth.status_code == 401
    me = await client.get("/users/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "c@example.com"
