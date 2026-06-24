import uuid

import pytest

from app.models import Attachment, Message

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
    big = b"x" * (1 * 1024 * 1024 + 1)  # 每檔上限 1MB
    resp = await client.post(
        "/uploads",
        files={"file": ("big.bin", big, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 413


async def test_upload_at_limit_ok(client, register_user, auth_headers):
    """恰好等於上限(1MB)可上傳成功(邊界含端點)。"""
    token = await register_user("atlimit@example.com", "AtLimit")
    exact = b"x" * (1 * 1024 * 1024)
    resp = await client.post(
        "/uploads",
        files={"file": ("exact.bin", exact, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["size"] == 1 * 1024 * 1024


async def test_upload_multichunk_roundtrip(client, register_user, auth_headers):
    """跨多個讀取分塊的檔案,內容須完整不變(驗證分塊讀取的重組正確)。"""
    token = await register_user("multi@example.com", "Multi")
    # 200KB,內容有變化以便偵測分塊邊界的錯置。
    content = bytes(range(256)) * 800
    up = await client.post(
        "/uploads",
        files={"file": ("blob.bin", content, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert up.status_code == 201, up.text
    assert up.json()["size"] == len(content)
    # 下載回來比對位元完全相同
    att_id = up.json()["id"]
    dl = await client.get(f"/attachments/{att_id}?token={token}")
    assert dl.status_code == 200
    assert dl.content == content


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


async def test_download_non_ascii_filename(client, register_user, auth_headers):
    """中文(非 ASCII)檔名下載不再 500,且 Content-Disposition 帶 RFC 6266 filename*。"""
    owner = await register_user("zh@example.com", "ZH")
    att = (await client.post(
        "/uploads",
        files={"file": ("報告.pdf", b"data", "application/pdf")},
        headers=auth_headers(owner),
    )).json()
    resp = await client.get(f"/attachments/{att['id']}", headers=auth_headers(owner))
    assert resp.status_code == 200
    assert resp.content == b"data"
    cd = resp.headers["content-disposition"]
    # UTF-8 百分比編碼的原名(報告 = %E5%A0%B1%E5%91%8A)。
    assert "filename*=UTF-8''" in cd
    assert "%E5%A0%B1%E5%91%8A" in cd


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


async def test_bound_attachment_member_permission(client, register_user, auth_headers, session_factory):
    """已綁定附件：對話成員可下載，非成員收到 404。"""
    # 建立三個使用者；alice + bob 互為好友（會自動建立 direct conversation）
    alice = await register_user("alice_ba@example.com", "Alice")
    bob = await register_user("bob_ba@example.com", "Bob")
    cara = await register_user("cara_ba@example.com", "Cara")

    # alice 加 bob 為好友，同時建立 direct conversation
    add_resp = await client.post(
        "/contacts",
        json={"email": "bob_ba@example.com"},
        headers=auth_headers(alice),
    )
    assert add_resp.status_code == 201, add_resp.text
    conv_id = add_resp.json()["conversation_id"]

    # alice 取得自己的 user id
    me_resp = await client.get("/users/me", headers=auth_headers(alice))
    assert me_resp.status_code == 200, me_resp.text
    alice_id = uuid.UUID(me_resp.json()["id"])

    # alice 上傳孤兒附件
    upload_resp = await client.post(
        "/uploads",
        files={"file": ("secret.txt", b"bound-content", "text/plain")},
        headers=auth_headers(alice),
    )
    assert upload_resp.status_code == 201, upload_resp.text
    att_id = uuid.UUID(upload_resp.json()["id"])

    # 透過 session_factory 直接在 DB 建一則 Message，並把附件 message_id 綁上去
    async with session_factory() as session:
        async with session.begin():
            msg = Message(
                conversation_id=uuid.UUID(conv_id),
                sender_id=alice_id,
                content="附件訊息",
            )
            session.add(msg)
            await session.flush()

            att = await session.get(Attachment, att_id)
            att.message_id = msg.id

    # bob（對話成員）可下載
    bob_resp = await client.get(f"/attachments/{att_id}", headers=auth_headers(bob))
    assert bob_resp.status_code == 200, bob_resp.text
    assert bob_resp.content == b"bound-content"

    # cara（非成員）收到 404
    cara_resp = await client.get(f"/attachments/{att_id}", headers=auth_headers(cara))
    assert cara_resp.status_code == 404, cara_resp.text
