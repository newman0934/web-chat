"""訊息置頂:service(權限/清單)+ WS pin/unpin + REST /pins(對應 BDD MP-01..10)。"""

import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message, User
from app.services.conversations import (
    create_group_conversation,
    get_or_create_direct_conversation,
)
from app.services.pins import PIN_LIMIT, can_pin, count_pins, list_pins

pytestmark = pytest.mark.asyncio
BASE = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)


def _recv(ws):
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "presence":
            return msg


async def _seed_direct_message(session_factory, content="hi"):
    """建 Alice-Bob direct 對話 + 一則 Bob 的訊息。回 (alice, bob, conv_id, msg_id)。"""
    async with session_factory() as db:
        alice = User(email=f"a-{uuid.uuid4().hex[:6]}@example.com", display_name="Alice", password_hash="x")
        bob = User(email=f"b-{uuid.uuid4().hex[:6]}@example.com", display_name="Bob", password_hash="x")
        db.add_all([alice, bob]); await db.flush()
        conv = await get_or_create_direct_conversation(db, alice.id, bob.id)
        m = Message(conversation_id=conv.id, sender_id=bob.id, content=content)
        db.add(m); await db.commit()
        return alice.id, bob.id, conv.id, m.id


# ── service 層 ────────────────────────────────────────────────────────────────
async def test_can_pin_direct_both(session_factory):
    a, b, conv_id, _ = await _seed_direct_message(session_factory)
    async with session_factory() as db:
        from app.models import Conversation
        conv = await db.get(Conversation, conv_id)
        assert await can_pin(db, conv, a) is True
        assert await can_pin(db, conv, b) is True


async def test_can_pin_group_admin_only(session_factory):
    async with session_factory() as db:
        admin = User(email=f"ad-{uuid.uuid4().hex[:6]}@e.com", display_name="Admin", password_hash="x")
        member = User(email=f"me-{uuid.uuid4().hex[:6]}@e.com", display_name="Member", password_hash="x")
        db.add_all([admin, member]); await db.flush()
        conv = await create_group_conversation(db, admin.id, "G", [member.id])
        await db.commit()
        assert await can_pin(db, conv, admin.id) is True
        assert await can_pin(db, conv, member.id) is False


async def test_list_pins_order(session_factory):
    a, b, conv_id, _ = await _seed_direct_message(session_factory)
    async with session_factory() as db:
        m1 = Message(conversation_id=conv_id, sender_id=b, content="p1")
        m2 = Message(conversation_id=conv_id, sender_id=b, content="p2")
        db.add_all([m1, m2]); await db.flush()
        m1.pinned_at = BASE
        m2.pinned_at = BASE.replace(minute=5)  # 較新
        await db.commit()
        pins = await list_pins(db, conv_id)
        assert [p.content for p in pins] == ["p2", "p1"]  # 新釘在前
        assert await count_pins(db, conv_id) == 2


# ── WS / REST 整合 ────────────────────────────────────────────────────────────
def _token(uid):
    from app.auth.security import create_access_token
    return create_access_token(uid)


async def _pins(client, auth_headers, token, conv_id):
    return (await client.get(f"/conversations/{conv_id}/pins", headers=auth_headers(token))).json()


async def test_pin_broadcasts_and_listed(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta, tb = _token(a), _token(b)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa, tc.websocket_connect(f"/ws?token={tb}") as wb:
            wa.send_json({"type": "pin", "message_id": str(mid)})
            for ws in (wa, wb):
                evt = _recv(ws)
                assert evt["type"] == "message_pinned"
                assert evt["message"]["id"] == str(mid)
                assert evt["message"]["pinned"] is True
    pins = await _pins(client, auth_headers, ta, conv_id)
    assert [p["id"] for p in pins] == [str(mid)]


async def test_unpin_broadcasts(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "pin", "message_id": str(mid)})
            _recv(wa)
            wa.send_json({"type": "unpin", "message_id": str(mid)})
            evt = _recv(wa)
            assert evt["type"] == "message_unpinned"
            assert evt["message_id"] == str(mid)
    assert await _pins(client, auth_headers, ta, conv_id) == []


async def test_group_non_admin_forbidden(client, auth_headers, session_factory):
    async with session_factory() as db:
        admin = User(email=f"ad-{uuid.uuid4().hex[:6]}@e.com", display_name="Admin", password_hash="x")
        member = User(email=f"me-{uuid.uuid4().hex[:6]}@e.com", display_name="Member", password_hash="x")
        db.add_all([admin, member]); await db.flush()
        conv = await create_group_conversation(db, admin.id, "G", [member.id])
        m = Message(conversation_id=conv.id, sender_id=member.id, content="hi")
        db.add(m); await db.commit()
        conv_id, mid, t_member, t_admin = conv.id, m.id, _token(member.id), _token(admin.id)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={t_member}") as wm:
            wm.send_json({"type": "pin", "message_id": str(mid)})
            assert _recv(wm)["reason"] == "forbidden"
    assert await _pins(client, auth_headers, t_admin, conv_id) == []  # 未被釘


async def test_pin_nonmember_not_found(client, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    async with session_factory() as db:
        carol = User(email=f"c-{uuid.uuid4().hex[:6]}@e.com", display_name="Carol", password_hash="x")
        db.add(carol); await db.commit()
        tc_token = _token(carol.id)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={tc_token}") as wc:
            wc.send_json({"type": "pin", "message_id": str(mid)})
            assert _recv(wc)["reason"] == "not_found"


async def test_pin_nonexistent_not_found(client, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "pin", "message_id": str(uuid.uuid4())})
            assert _recv(wa)["reason"] == "not_found"


async def test_pin_limit(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta = _token(a)
    # 先直接釘滿 10 則
    async with session_factory() as db:
        for i in range(PIN_LIMIT):
            m = Message(conversation_id=conv_id, sender_id=b, content=f"p{i}")
            m.pinned_at = BASE.replace(second=i)
            db.add(m)
        await db.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "pin", "message_id": str(mid)})  # 第 11 則
            assert _recv(wa)["reason"] == "pin_limit"


async def test_unpin_then_pin_new_ok(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta = _token(a)
    pinned_ids = []
    async with session_factory() as db:
        for i in range(PIN_LIMIT):
            m = Message(conversation_id=conv_id, sender_id=b, content=f"p{i}")
            m.pinned_at = BASE.replace(second=i)
            db.add(m); await db.flush()
            pinned_ids.append(str(m.id))
        await db.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "unpin", "message_id": pinned_ids[0]})
            assert _recv(wa)["type"] == "message_unpinned"
            wa.send_json({"type": "pin", "message_id": str(mid)})  # 釘新的
            assert _recv(wa)["type"] == "message_pinned"
    assert await count_pins_via(session_factory, conv_id) == PIN_LIMIT


async def count_pins_via(session_factory, conv_id):
    async with session_factory() as db:
        return await count_pins(db, conv_id)


async def test_idempotent_repin(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "pin", "message_id": str(mid)})
            assert _recv(wa)["type"] == "message_pinned"
            wa.send_json({"type": "pin", "message_id": str(mid)})  # 再釘一次
            assert _recv(wa)["type"] == "message_pinned"  # 冪等,仍廣播
    pins = await _pins(client, auth_headers, ta, conv_id)
    assert len(pins) == 1  # 不重複計數


async def test_delete_pinned_auto_unpin(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    ta, tb = _token(a), _token(b)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "pin", "message_id": str(mid)})
            _recv(wa)
        # Bob(sender)刪除已釘訊息 → 自動解釘並廣播
        with tc.websocket_connect(f"/ws?token={tb}") as wb:
            wb.send_json({"type": "delete", "message_id": str(mid)})
            evts = [_recv(wb), _recv(wb)]
            types = {e["type"] for e in evts}
            assert "message_updated" in types and "message_unpinned" in types
    assert await _pins(client, auth_headers, ta, conv_id) == []


async def test_get_pins_nonmember_404(client, auth_headers, session_factory):
    a, b, conv_id, mid = await _seed_direct_message(session_factory)
    async with session_factory() as db:
        carol = User(email=f"c-{uuid.uuid4().hex[:6]}@e.com", display_name="Carol", password_hash="x")
        db.add(carol); await db.commit()
        tcarol = _token(carol.id)
    resp = await client.get(f"/conversations/{conv_id}/pins", headers=auth_headers(tcarol))
    assert resp.status_code == 404
