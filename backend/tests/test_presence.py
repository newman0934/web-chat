"""線上狀態(presence)測試。

Task 1：User.last_seen_at 欄位(schema 由 conftest 的 create_all 建立)。
Task 2：ConnectionManager first/last 旗標、presence service 純後端邏輯。
後續 task 會補 WS 廣播、/contacts 帶 presence。
"""

import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app.main import app
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


def test_manager_mark_and_get_last_seen():
    """manager 以記憶體保存 last_seen;未設者為 None。"""
    mgr = ConnectionManager()
    uid = uuid.uuid4()
    assert mgr.get_last_seen(uid) is None
    ts = datetime.now(timezone.utc)
    mgr.mark_last_seen(uid, ts)
    assert mgr.get_last_seen(uid) == ts


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


# --- Task 3：WS 廣播 + /contacts 帶 presence ---


async def _pair(client, register_user, auth_headers, a, b):
    """註冊兩人並加好友,回 (tokenA, tokenB, conv_id)。"""
    ta = await register_user(a, "Alice")
    tb = await register_user(b, "Bob")
    resp = await client.post("/contacts", json={"email": b}, headers=auth_headers(ta))
    return ta, tb, resp.json()["conversation_id"]


async def _uid(session_factory, email):
    from sqlalchemy import select

    async with session_factory() as db:
        res = await db.execute(select(User).where(User.email == email))
        return str(res.scalar_one().id)


@pytest.mark.asyncio
async def test_first_connect_broadcasts_online_to_online_friend(
    client, register_user, auth_headers, session_factory
):
    """PR-01:好友首條連線上線 → 在線的我收到 presence online。"""
    ta, tb, _ = await _pair(client, register_user, auth_headers,
                            "pa@example.com", "pb@example.com")
    bob_id = await _uid(session_factory, "pb@example.com")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as ws_alice:
            with tc.websocket_connect(f"/ws?token={tb}"):
                evt = ws_alice.receive_json()
    assert evt["type"] == "presence"
    assert evt["user_id"] == bob_id
    assert evt["online"] is True
    assert evt["last_seen_at"] is None


@pytest.mark.asyncio
async def test_last_disconnect_sets_last_seen_and_broadcasts_offline(
    client, register_user, auth_headers, session_factory
):
    """PR-02:好友末條連線斷開 → 我收到 offline + last_seen_at;DB 更新。"""
    ta, tb, _ = await _pair(client, register_user, auth_headers,
                            "pa@example.com", "pb@example.com")
    bob_id = await _uid(session_factory, "pb@example.com")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as ws_alice:
            with tc.websocket_connect(f"/ws?token={tb}"):
                ws_alice.receive_json()  # online
            evt = ws_alice.receive_json()  # bob 離線
    assert evt["type"] == "presence"
    assert evt["user_id"] == bob_id
    assert evt["online"] is False
    assert evt["last_seen_at"] is not None
    # manager(記憶體)也記下了 Bob 的 last_seen
    from app.ws.manager import manager

    assert manager.get_last_seen(uuid.UUID(bob_id)) is not None


@pytest.mark.asyncio
async def test_second_connection_no_duplicate_online(
    client, register_user, auth_headers, session_factory
):
    """PR-04:同一好友第二條連線不重播 online。"""
    ta, tb, conv = await _pair(client, register_user, auth_headers,
                               "pa@example.com", "pb@example.com")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as ws_alice:
            with tc.websocket_connect(f"/ws?token={tb}") as ws_bob1:
                ws_alice.receive_json()  # online(首條)
                with tc.websocket_connect(f"/ws?token={tb}"):  # 第二條,不應廣播
                    ws_bob1.send_json({"type": "message", "conversation_id": conv,
                                       "content": "hi", "temp_id": "t"})
                    ws_bob1.receive_json()  # ack
                    frame = ws_alice.receive_json()
    # 若第二條誤播 online,alice 的下一個 frame 會是 presence 而非 message
    assert frame["type"] == "message"


@pytest.mark.asyncio
async def test_non_last_disconnect_no_false_offline(
    client, register_user, auth_headers, session_factory
):
    """PR-05:仍有其他連線時,某條斷開不誤報 offline。"""
    ta, tb, conv = await _pair(client, register_user, auth_headers,
                               "pa@example.com", "pb@example.com")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as ws_alice:
            with tc.websocket_connect(f"/ws?token={tb}") as ws_bob1:
                ws_alice.receive_json()  # online
                with tc.websocket_connect(f"/ws?token={tb}"):
                    pass  # 第二條開→關:非首非尾,皆不廣播
                ws_bob1.send_json({"type": "message", "conversation_id": conv,
                                   "content": "hi", "temp_id": "t"})
                ws_bob1.receive_json()  # ack
                frame = ws_alice.receive_json()
    assert frame["type"] == "message"  # 非 offline


@pytest.mark.asyncio
async def test_non_friend_presence_not_broadcast(
    client, register_user, auth_headers, session_factory
):
    """PR-06:非好友上線不廣播給我。"""
    ta, tb, _ = await _pair(client, register_user, auth_headers,
                            "pa@example.com", "pb@example.com")
    tc_token = await register_user("pc@example.com", "Carol")  # 非好友
    bob_id = await _uid(session_factory, "pb@example.com")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={ta}") as ws_alice:
            with tc.websocket_connect(f"/ws?token={tc_token}"):  # 非好友先上線
                with tc.websocket_connect(f"/ws?token={tb}"):  # 好友後上線
                    evt = ws_alice.receive_json()
    # alice 的第一個 frame 必為 bob(好友);carol 不該外洩
    assert evt["type"] == "presence"
    assert evt["user_id"] == bob_id


@pytest.mark.asyncio
async def test_contacts_carries_online_and_last_seen(
    client, register_user, auth_headers, session_factory
):
    """PR-03/08:GET /contacts 每筆含 online / last_seen_at;從未上線者 false/null。"""
    ta, tb, _ = await _pair(client, register_user, auth_headers,
                            "pa@example.com", "pb@example.com")
    # 再加一個從未上線的好友 Carol
    await register_user("pc@example.com", "Carol")
    await client.post("/contacts", json={"email": "pc@example.com"}, headers=auth_headers(ta))

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={tb}"):  # Bob 在線
            resp = await client.get("/contacts", headers=auth_headers(ta))
    assert resp.status_code == 200
    by_email = {c["email"]: c for c in resp.json()}
    assert by_email["pb@example.com"]["online"] is True
    assert by_email["pc@example.com"]["online"] is False
    assert by_email["pc@example.com"]["last_seen_at"] is None
