import pytest

pytestmark = pytest.mark.asyncio


async def test_upload_returns_metadata(client, register_user, auth_headers):
    token = await register_user("up@example.com", "Up")
    resp = await client.post(
        "/uploads",
        files={"file": ("hello.txt", b"hello world", "text/plain")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["original_name"] == "hello.txt"
    assert data["is_image"] is False
    assert data["size"] == 11
    assert "id" in data


async def test_upload_detects_image(client, register_user, auth_headers):
    token = await register_user("img@example.com", "Img")
    resp = await client.post(
        "/uploads",
        files={"file": ("a.png", b"\x89PNG\r\n", "image/png")},
        headers=auth_headers(token),
    )
    assert resp.json()["is_image"] is True


async def test_upload_too_large_413(client, register_user, auth_headers):
    token = await register_user("big@example.com", "Big")
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        "/uploads",
        files={"file": ("big.bin", big, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 413


async def test_download_orphan_only_uploader(client, register_user, auth_headers):
    owner = await register_user("own@example.com", "Own")
    other = await register_user("oth@example.com", "Oth")
    att = (await client.post(
        "/uploads",
        files={"file": ("f.txt", b"secret", "text/plain")},
        headers=auth_headers(owner),
    )).json()
    # 上傳者可下載
    ok = await client.get(f"/attachments/{att['id']}", headers=auth_headers(owner))
    assert ok.status_code == 200
    assert ok.content == b"secret"
    # 他人不可（孤兒附件）
    no = await client.get(f"/attachments/{att['id']}", headers=auth_headers(other))
    assert no.status_code == 404


async def test_download_accepts_query_token(client, register_user, auth_headers):
    owner = await register_user("q@example.com", "Q")
    att = (await client.post(
        "/uploads",
        files={"file": ("f.txt", b"hi", "text/plain")},
        headers=auth_headers(owner),
    )).json()
    resp = await client.get(f"/attachments/{att['id']}?token={owner}")
    assert resp.status_code == 200
    assert resp.content == b"hi"
