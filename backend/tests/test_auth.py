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


async def test_login_rate_limited_after_failures(client, register_user):
    await register_user("rl@example.com", "RL")
    # 連續 10 次錯密碼 → 401;第 11 次起被速率限制擋下 → 429。
    for _ in range(10):
        r = await client.post(
            "/auth/login", json={"email": "rl@example.com", "password": "wrong"}
        )
        assert r.status_code == 401
    blocked = await client.post(
        "/auth/login", json={"email": "rl@example.com", "password": "wrong"}
    )
    assert blocked.status_code == 429
    # 被擋期間即使密碼正確也回 429(擋在驗證之前)。
    even_correct = await client.post(
        "/auth/login", json={"email": "rl@example.com", "password": "secret123"}
    )
    assert even_correct.status_code == 429


async def test_login_success_does_not_count_toward_limit(client, register_user):
    await register_user("ok@example.com", "OK")
    # 成功登入多次不應被擋(只記失敗)。
    for _ in range(15):
        r = await client.post(
            "/auth/login", json={"email": "ok@example.com", "password": "secret123"}
        )
        assert r.status_code == 200


async def test_register_rate_limited(client):
    # 同一 IP 連續註冊到上限(20)皆成功;第 21 次被速率限制擋下 → 429。
    for i in range(20):
        r = await client.post(
            "/auth/register",
            json={
                "email": f"reg{i}@example.com",
                "display_name": f"U{i}",
                "password": "secret123",
            },
        )
        assert r.status_code == 201, r.text
    blocked = await client.post(
        "/auth/register",
        json={"email": "over@example.com", "display_name": "Over", "password": "secret123"},
    )
    assert blocked.status_code == 429


async def test_users_me_requires_token(client, register_user, auth_headers):
    token = await register_user("c@example.com", "Carol")
    unauth = await client.get("/users/me")
    assert unauth.status_code == 401
    me = await client.get("/users/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "c@example.com"
