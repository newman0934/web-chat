"""線上狀態(presence)測試。

Task 1：User.last_seen_at 欄位(schema 由 conftest 的 create_all 建立)。
Task 2：ConnectionManager first/last 旗標、presence service 純後端邏輯。
後續 task 會補 WS 廣播、/contacts 帶 presence。
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Contact, User
from app.services import presence as presence_svc
from app.ws.manager import ConnectionManager


class FakeWebSocket:
    """最小可用的 WebSocket 替身:支援 accept / send_json,記錄送出的 payload。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def _make_user(db, name: str = "U") -> User:
    u = User(
        email=f"p-{uuid.uuid4().hex[:8]}@e2e.test",
        display_name=name,
        password_hash="x",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_user_last_seen_defaults_null(session_factory):
    """User 預設 last_seen_at 為 None,可寫入時間。"""
    async with session_factory() as db:
        u = await _make_user(db, "P")
        assert u.last_seen_at is None


# --- Task 2：ConnectionManager first/last ---


@pytest.mark.asyncio
async def test_connect_returns_is_first_only_on_zero_to_one():
    """connect:第一條連線回 True,同 user 第二條回 False。"""
    mgr = ConnectionManager()
    uid = uuid.uuid4()
    assert await mgr.connect(uid, FakeWebSocket()) is True
    assert await mgr.connect(uid, FakeWebSocket()) is False


def test_disconnect_returns_is_last_only_on_one_to_zero():
    """disconnect:倒數第二條斷回 False,最後一條斷回 True。"""
    mgr = ConnectionManager()
    uid = uuid.uuid4()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    # 手動塞兩條連線(避開 async accept)。
    mgr._connections[uid].update({ws1, ws2})
    assert mgr.disconnect(uid, ws1) is False
    assert mgr.disconnect(uid, ws2) is True


def test_disconnect_unknown_returns_false():
    """斷一條不存在的連線:回 False,不丟例外。"""
    mgr = ConnectionManager()
    assert mgr.disconnect(uuid.uuid4(), FakeWebSocket()) is False


# --- Task 2：presence service ---


@pytest.mark.asyncio
async def test_get_friend_ids(session_factory):
    """get_friend_ids 只回該 user 單向 contact 的對象集合。"""
    async with session_factory() as db:
        me = await _make_user(db, "me")
        f1 = await _make_user(db, "f1")
        f2 = await _make_user(db, "f2")
        stranger = await _make_user(db, "s")
        db.add(Contact(user_id=me.id, contact_user_id=f1.id))
        db.add(Contact(user_id=me.id, contact_user_id=f2.id))
        db.add(Contact(user_id=stranger.id, contact_user_id=me.id))
        await db.commit()

        ids = await presence_svc.get_friend_ids(db, me.id)
        assert ids == {f1.id, f2.id}


@pytest.mark.asyncio
async def test_set_last_seen_writes_and_returns_now(session_factory):
    """set_last_seen 寫入 now 並回傳;回傳為 tz-aware UTC。"""
    async with session_factory() as db:
        u = await _make_user(db, "u")
        before = datetime.now(timezone.utc)
        ts = await presence_svc.set_last_seen(db, u.id)
        await db.commit()
        assert ts is not None
        assert ts.tzinfo is not None
        assert ts >= before
        refreshed = await db.get(User, u.id)
        await db.refresh(refreshed)
        assert refreshed.last_seen_at is not None


def test_build_presence_event_online():
    """online 事件:last_seen_at 為 None。"""
    uid = uuid.uuid4()
    evt = presence_svc.build_presence_event(uid, True, None)
    assert evt == {
        "type": "presence",
        "user_id": str(uid),
        "online": True,
        "last_seen_at": None,
    }


def test_build_presence_event_offline_iso():
    """offline 事件:last_seen_at 序列化成 tz-aware UTC ISO。"""
    uid = uuid.uuid4()
    dt = datetime(2026, 6, 23, 1, 2, 3, tzinfo=timezone.utc)
    evt = presence_svc.build_presence_event(uid, False, dt)
    assert evt["online"] is False
    assert evt["last_seen_at"] == "2026-06-23T01:02:03+00:00"


def test_build_presence_event_naive_last_seen_treated_utc():
    """naive(SQLite)last_seen 視為 UTC,不被本機時區位移。"""
    uid = uuid.uuid4()
    naive = datetime(2026, 6, 23, 1, 2, 3)
    evt = presence_svc.build_presence_event(uid, False, naive)
    assert evt["last_seen_at"] == "2026-06-23T01:02:03+00:00"


@pytest.mark.asyncio
async def test_presence_for_contacts_batch(session_factory):
    """presence_for_contacts 批次回每個 id 的 last_seen(未設為 None)。"""
    async with session_factory() as db:
        a = await _make_user(db, "a")
        b = await _make_user(db, "b")
        await presence_svc.set_last_seen(db, a.id)
        await db.commit()

        m = await presence_svc.presence_for_contacts(db, {a.id, b.id})
        assert set(m.keys()) == {a.id, b.id}
        assert m[a.id] is not None
        assert m[b.id] is None
