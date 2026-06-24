"""訊息搜尋 service 與端點測試(對應 BDD MS-01..06、09、10)。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.security import create_access_token
from app.models import Message, User
from app.services.conversations import (
    create_group_conversation,
    get_or_create_direct_conversation,
)
from app.services.search import escape_like, search_messages

pytestmark = pytest.mark.asyncio

BASE = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


def _mk_user(db, name: str) -> User:
    u = User(
        email=f"{name}-{uuid.uuid4().hex[:6]}@example.com",
        display_name=name,
        password_hash="x",
    )
    db.add(u)
    return u


def _mk_msg(db, conv, sender, content, mins, *, deleted=False) -> Message:
    m = Message(conversation_id=conv.id, sender_id=sender.id, content=content)
    m.created_at = BASE + timedelta(minutes=mins)
    if deleted:
        m.deleted_at = BASE + timedelta(minutes=mins, seconds=30)
    db.add(m)
    return m


# ── service 層 ────────────────────────────────────────────────────────────────
async def test_search_content_match(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "明天的會議改到下午三點", 1)
        _mk_msg(db, conv, alice, "好的沒問題", 2)
        await db.commit()

        resp = await search_messages(db, alice.id, "會議", None, 20)
        contents = [r.message.content for r in resp.items]
        assert "明天的會議改到下午三點" in contents
        assert "好的沒問題" not in contents
        # 結果附對話資訊:direct → other_user 為對方 Bob
        r = next(r for r in resp.items if "會議" in r.message.content)
        assert r.conversation.type == "direct"
        assert r.conversation.other_user.display_name == "Bob"


async def test_search_sender_name_match(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "收到", 1)  # 內容不含 "Bob",靠寄件者名命中
        await db.commit()

        resp = await search_messages(db, alice.id, "Bob", None, 20)
        assert any(r.message.content == "收到" for r in resp.items)


async def test_search_case_insensitive(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "Hello World", 1)
        await db.commit()

        lower = await search_messages(db, alice.id, "hello", None, 20)
        upper = await search_messages(db, alice.id, "HELLO", None, 20)
        assert len(lower.items) == 1 and len(upper.items) == 1


async def test_search_excludes_deleted(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "這則稍後會刪", 1, deleted=True)
        await db.commit()

        resp = await search_messages(db, alice.id, "稍後會刪", None, 20)
        assert resp.items == []


async def test_search_permission_isolation(session_factory):
    async with session_factory() as db:
        alice, bob, carol = _mk_user(db, "Alice"), _mk_user(db, "Bob"), _mk_user(db, "Carol")
        await db.flush()
        ab = await get_or_create_direct_conversation(db, alice.id, bob.id)
        bc = await get_or_create_direct_conversation(db, bob.id, carol.id)
        _mk_msg(db, ab, bob, "Alice 看得到這句機密", 1)
        _mk_msg(db, bc, bob, "Alice 不該看到這句機密", 2)
        await db.commit()

        resp = await search_messages(db, alice.id, "機密", None, 20)
        contents = [r.message.content for r in resp.items]
        assert "Alice 看得到這句機密" in contents
        assert "Alice 不該看到這句機密" not in contents  # 非該對話成員


async def test_search_escapes_wildcards(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "折扣 50% 起", 1)
        _mk_msg(db, conv, bob, "訂單編號 5012345", 2)  # 含 "50" 但無 "50%"
        await db.commit()

        resp = await search_messages(db, alice.id, "50%", None, 20)
        contents = [r.message.content for r in resp.items]
        assert "折扣 50% 起" in contents
        # % 被逸出當一般字元:不會把 "5012345" 當 "50<任意>" 誤命中
        assert "訂單編號 5012345" not in contents


async def test_search_pagination(session_factory):
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        for i in range(25):
            _mk_msg(db, conv, bob, f"報表 第{i}版", i + 1)
        await db.commit()

        page1 = await search_messages(db, alice.id, "報表", None, 20)
        assert len(page1.items) == 20
        assert page1.next_before is not None
        page2 = await search_messages(db, alice.id, "報表", page1.next_before, 20)
        assert len(page2.items) == 5
        assert page2.next_before is None
        ids1 = {r.message.id for r in page1.items}
        ids2 = {r.message.id for r in page2.items}
        assert ids1.isdisjoint(ids2)  # 不重複


def test_escape_like():
    assert escape_like("50%") == "50\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("c\\d") == "c\\\\d"


# ── 端點層 ────────────────────────────────────────────────────────────────────
async def _seed_alice_with_token(session_factory):
    """建 Alice 與一則她可見的訊息,回 (alice_id, token)。"""
    async with session_factory() as db:
        alice, bob = _mk_user(db, "Alice"), _mk_user(db, "Bob")
        await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        _mk_msg(db, conv, bob, "季度檢討會議紀錄", 1)
        await db.commit()
        return alice.id, create_access_token(alice.id)


async def test_search_endpoint_unauthorized(client):
    resp = await client.get("/search/messages?q=會議")
    assert resp.status_code == 401


async def test_search_endpoint_empty_q(client, session_factory, auth_headers):
    _, token = await _seed_alice_with_token(session_factory)
    h = auth_headers(token)
    assert (await client.get("/search/messages?q=", headers=h)).status_code == 422
    # 全空白 → strip 後為空 → 422
    assert (await client.get("/search/messages?q=%20%20", headers=h)).status_code == 422
    # 過長(> 100 字)→ 422
    long_q = "a" * 101
    assert (await client.get(f"/search/messages?q={long_q}", headers=h)).status_code == 422


async def test_search_endpoint_happy(client, session_factory, auth_headers):
    _, token = await _seed_alice_with_token(session_factory)
    resp = await client.get("/search/messages?q=會議", headers=auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert "季度檢討會議紀錄" == item["message"]["content"]
    assert item["conversation"]["type"] == "direct"
    assert item["conversation"]["other_user"]["display_name"] == "Bob"
    assert item["sender_name"] == "Bob"  # 寄件者名(群組也帶得到)
