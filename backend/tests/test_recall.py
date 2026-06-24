"""訊息撤回:WS recall + 操作守衛 + 搜尋排除(對應 BDD MR-01..08)。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app.auth.security import create_access_token
from app.main import app
from app.models import Attachment, Conversation, Message, Reaction, User
from app.services.conversations import (
    create_group_conversation,
    get_or_create_direct_conversation,
)
from app.services.pins import count_pins
from app.services.search import search_messages

pytestmark = pytest.mark.asyncio


def _recv(ws):
    while True:
        msg = ws.receive_json()
        if msg.get("type") != "presence":
            return msg


def _recv_type(ws, wanted: str, tries: int = 5):
    """收下一個指定 type 的 frame(略過其他,如 message_updated 後接的 message_unpinned)。"""
    for _ in range(tries):
        msg = _recv(ws)
        if msg.get("type") == wanted:
            return msg
    raise AssertionError(f"未收到 type={wanted}")


def _token(uid):
    return create_access_token(uid)


async def _direct(session_factory):
    async with session_factory() as db:
        a = User(email=f"a-{uuid.uuid4().hex[:6]}@e.com", display_name="Alice", password_hash="x")
        b = User(email=f"b-{uuid.uuid4().hex[:6]}@e.com", display_name="Bob", password_hash="x")
        db.add_all([a, b]); await db.flush()
        conv = await get_or_create_direct_conversation(db, a.id, b.id)
        await db.commit()
        return a.id, b.id, conv.id


def _ws_send(ws, token, conv_id, content) -> str:
    ws.send_json({"type": "message", "conversation_id": str(conv_id), "content": content, "temp_id": "t1"})
    ack = _recv_type(ws, "ack")
    return ack["message"]["id"]


# ── MR-01:撤回成功並廣播 ─────────────────────────────────────────────────
async def test_recall_broadcasts_and_masks(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta, tb = _token(a), _token(b)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa, tc.websocket_connect(f"/ws?token={tb}") as wb:
            mid = _ws_send(wa, ta, conv_id, "誤傳的內容")
            _recv_type(wb, "message")  # bob 收到原訊息
            wa.send_json({"type": "recall", "message_id": mid})
            for ws in (wa, wb):
                evt = _recv_type(ws, "message_updated")
                assert evt["message"]["id"] == mid
                assert evt["message"]["recalled"] is True
                assert evt["message"]["content"] == ""
                assert evt["message"]["attachments"] == []
                assert evt["message"]["reactions"] == []


# ── MR-02:非寄件人撤回被拒 ──────────────────────────────────────────────
async def test_recall_non_sender_forbidden(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta, tb = _token(a), _token(b)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa, tc.websocket_connect(f"/ws?token={tb}") as wb:
            mid = _ws_send(wa, ta, conv_id, "abc")
            _recv_type(wb, "message")
            wb.send_json({"type": "recall", "message_id": mid})
            assert _recv_type(wb, "error")["reason"] == "forbidden"


# ── MR-03:逾時撤回被拒 ──────────────────────────────────────────────────
async def test_recall_window_passed(session_factory):
    a, b, conv_id = await _direct(session_factory)
    # 直接種一則 3 分鐘前由 Alice 送的訊息
    async with session_factory() as db:
        m = Message(conversation_id=conv_id, sender_id=a, content="old")
        m.created_at = datetime.now(timezone.utc) - timedelta(minutes=3)
        db.add(m); await db.commit()
        mid = str(m.id)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "recall", "message_id": mid})
            assert _recv_type(wa, "error")["reason"] == "recall_window_passed"


# ── MR-04:撤回後不可再 edit/react/pin ───────────────────────────────────
async def test_recalled_blocks_other_actions(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            mid = _ws_send(wa, ta, conv_id, "to recall")
            wa.send_json({"type": "recall", "message_id": mid})
            _recv_type(wa, "message_updated")
            for op in (
                {"type": "edit", "message_id": mid, "content": "x"},
                {"type": "react", "message_id": mid, "emoji": "👍"},
                {"type": "pin", "message_id": mid},
            ):
                wa.send_json(op)
                assert _recv_type(wa, "error").get("reason") in {"forbidden", "not_found"}


# ── MR-05:撤回已刪除訊息被拒 ────────────────────────────────────────────
async def test_recall_deleted_forbidden(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            mid = _ws_send(wa, ta, conv_id, "del then recall")
            wa.send_json({"type": "delete", "message_id": mid})
            _recv_type(wa, "message_updated")
            wa.send_json({"type": "recall", "message_id": mid})
            assert _recv_type(wa, "error")["reason"] == "forbidden"


# ── MR-06:重複撤回被拒 ──────────────────────────────────────────────────
async def test_recall_twice_forbidden(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            mid = _ws_send(wa, ta, conv_id, "once")
            wa.send_json({"type": "recall", "message_id": mid})
            _recv_type(wa, "message_updated")
            wa.send_json({"type": "recall", "message_id": mid})
            assert _recv_type(wa, "error")["reason"] == "forbidden"


# ── MR-07:已撤回不出現在搜尋 ────────────────────────────────────────────
async def test_recalled_excluded_from_search(session_factory):
    a, b, conv_id = await _direct(session_factory)
    ta = _token(a)
    kw = "搜尋撤回關鍵字XYZ"
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            mid = _ws_send(wa, ta, conv_id, kw)
            wa.send_json({"type": "recall", "message_id": mid})
            _recv_type(wa, "message_updated")
    async with session_factory() as db:
        resp = await search_messages(db, a, kw, None, 20)
        assert resp.items == []


# ── MR-08:撤回已釘自動解釘 ──────────────────────────────────────────────
async def test_recall_pinned_auto_unpins(session_factory):
    # 群組:Alice admin、Bob member;Bob 送訊息、Alice 釘、Bob 在時窗內撤回 → 自動解釘
    async with session_factory() as db:
        admin = User(email=f"ad-{uuid.uuid4().hex[:6]}@e.com", display_name="Admin", password_hash="x")
        bob = User(email=f"bo-{uuid.uuid4().hex[:6]}@e.com", display_name="Bob", password_hash="x")
        db.add_all([admin, bob]); await db.flush()
        conv = await create_group_conversation(db, admin.id, "G", [bob.id])
        await db.commit()
        conv_id, t_admin, t_bob = conv.id, _token(admin.id), _token(bob.id)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={t_admin}") as wad, tc.websocket_connect(f"/ws?token={t_bob}") as wbob:
            mid = _ws_send(wbob, t_bob, conv_id, "pin then recall")
            _recv_type(wad, "message")
            wad.send_json({"type": "pin", "message_id": mid})
            _recv_type(wad, "message_pinned")
            _recv_type(wbob, "message_pinned")
            # Bob(寄件人)撤回 → message_updated + message_unpinned
            wbob.send_json({"type": "recall", "message_id": mid})
            got = [_recv(wbob), _recv(wbob)]
            assert {"message_updated", "message_unpinned"} <= {e["type"] for e in got}
    async with session_factory() as db:
        assert await count_pins(db, conv_id) == 0


# ── 附件 / 表情於撤回後被移除(資料層) ──────────────────────────────────
async def test_recall_removes_attachment_and_reactions(session_factory):
    a, b, conv_id = await _direct(session_factory)
    async with session_factory() as db:
        m = Message(conversation_id=conv_id, sender_id=a, content="with stuff")
        m.created_at = datetime.now(timezone.utc)
        db.add(m); await db.flush()
        db.add(Attachment(message_id=m.id, uploader_id=a, stored_name="s", original_name="f.png",
                          content_type="image/png", size=3, is_image=True))
        db.add(Reaction(message_id=m.id, user_id=b, emoji="👍"))
        await db.commit()
        mid = str(m.id)
    ta = _token(a)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as wa:
            wa.send_json({"type": "recall", "message_id": mid})
            _recv_type(wa, "message_updated")
    async with session_factory() as db:
        from sqlalchemy import func, select
        atts = (await db.execute(select(func.count()).select_from(Attachment).where(Attachment.message_id == uuid.UUID(mid)))).scalar_one()
        reacts = (await db.execute(select(func.count()).select_from(Reaction).where(Reaction.message_id == uuid.UUID(mid)))).scalar_one()
        assert atts == 0 and reacts == 0
