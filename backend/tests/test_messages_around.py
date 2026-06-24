"""訊息列表 around(視窗載入)/ after(向下分頁)/ 互斥 與 404(對應 BDD MS-08、MS-11)。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.security import create_access_token
from app.models import Message, User
from app.services.conversations import get_or_create_direct_conversation

pytestmark = pytest.mark.asyncio

BASE = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


async def _seed(session_factory):
    """建 Alice-Bob direct 對話 + 10 則訊息(m0..m9,時間遞增)。回 (token, conv_id, [msg...])。"""
    async with session_factory() as db:
        alice = User(email=f"a-{uuid.uuid4().hex[:6]}@example.com", display_name="Alice", password_hash="x")
        bob = User(email=f"b-{uuid.uuid4().hex[:6]}@example.com", display_name="Bob", password_hash="x")
        db.add_all([alice, bob])
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        msgs = []
        for i in range(10):
            m = Message(conversation_id=conv.id, sender_id=bob.id, content=f"m{i}")
            m.created_at = BASE + timedelta(minutes=i)
            db.add(m)
            msgs.append(m)
        await db.commit()
        return (
            create_access_token(alice.id),
            conv.id,
            [(m.id, m.content, m.created_at) for m in msgs],
        )


async def test_around_window(client, session_factory, auth_headers):
    token, conv_id, msgs = await _seed(session_factory)
    m5_id = msgs[5][0]
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"around": str(m5_id), "limit": 6},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    contents = [m["content"] for m in resp.json()]
    # k=3:older(<=m5)取 3 = m3,m4,m5;newer(>m5)取 3 = m6,m7,m8
    assert contents == ["m3", "m4", "m5", "m6", "m7", "m8"]


async def test_around_first_message_boundary(client, session_factory, auth_headers):
    token, conv_id, msgs = await _seed(session_factory)
    m0_id = msgs[0][0]
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"around": str(m0_id), "limit": 6},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    contents = [m["content"] for m in resp.json()]
    # 第一則:只有單側鄰居(自己 + 之後),不報錯
    assert contents[0] == "m0"
    assert contents == ["m0", "m1", "m2", "m3"]


async def test_around_same_timestamp_includes_target(client, session_factory, auth_headers):
    """同秒多則(created_at 相同 tie)時,around 視窗一定包含錨點訊息本身。"""
    async with session_factory() as db:
        alice = User(email=f"a-{uuid.uuid4().hex[:6]}@example.com", display_name="Alice", password_hash="x")
        bob = User(email=f"b-{uuid.uuid4().hex[:6]}@example.com", display_name="Bob", password_hash="x")
        db.add_all([alice, bob])
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        msgs = []
        for i in range(8):
            m = Message(conversation_id=conv.id, sender_id=bob.id, content=f"tie{i}")
            m.created_at = BASE  # 全部同一時間
            db.add(m)
            msgs.append(m)
        await db.commit()
        token = create_access_token(alice.id)
        conv_id, ids = conv.id, [m.id for m in msgs]

    # 對每一則當錨點,視窗(limit=4)都必須包含它自己。
    for target_id in ids:
        resp = await client.get(
            f"/conversations/{conv_id}/messages",
            params={"around": str(target_id), "limit": 4},
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        returned = {m["id"] for m in resp.json()}
        assert str(target_id) in returned


async def test_around_404_nonexistent(client, session_factory, auth_headers):
    token, conv_id, _ = await _seed(session_factory)
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"around": str(uuid.uuid4())},
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


async def test_around_404_other_conversation(client, session_factory, auth_headers):
    token, conv_id, _ = await _seed(session_factory)
    # 另開一個對話與訊息,用它的 message id 對 conv_id 查 → target 不屬此對話 → 404
    token2, other_conv, other_msgs = await _seed(session_factory)
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"around": str(other_msgs[0][0])},
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


async def test_after_pagination(client, session_factory, auth_headers):
    token, conv_id, msgs = await _seed(session_factory)
    m5_created = msgs[5][2]
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"after": m5_created.isoformat(), "limit": 30},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    contents = [m["content"] for m in resp.json()]
    assert contents == ["m6", "m7", "m8", "m9"]  # 較新、升序


async def test_mutual_exclusion_422(client, session_factory, auth_headers):
    token, conv_id, msgs = await _seed(session_factory)
    resp = await client.get(
        f"/conversations/{conv_id}/messages",
        params={"before": BASE.isoformat(), "around": str(msgs[0][0])},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
