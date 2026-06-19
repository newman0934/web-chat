import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import Message, User
from app.services import conversations as svc


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


pytestmark = pytest.mark.asyncio


async def _user(session, email):
    u = User(email=email, display_name=email[0], password_hash="h")
    session.add(u)
    await session.flush()
    return u


async def test_direct_key_is_order_independent():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert svc.direct_key(a, b) == svc.direct_key(b, a)


async def test_get_or_create_direct_is_idempotent(session):
    a, b = await _user(session, "a@x.com"), await _user(session, "b@x.com")
    c1 = await svc.get_or_create_direct_conversation(session, a.id, b.id)
    c2 = await svc.get_or_create_direct_conversation(session, b.id, a.id)
    assert c1.id == c2.id
    assert c1.type == "direct"
    assert sorted(await svc.get_member_ids(session, c1.id)) == sorted([a.id, b.id])


async def test_create_group_sets_members_and_creator(session):
    a = await _user(session, "a@x.com")
    b = await _user(session, "b@x.com")
    c = await _user(session, "c@x.com")
    conv = await svc.create_group_conversation(session, a.id, "群", [b.id, c.id])
    assert conv.type == "group" and conv.name == "群" and conv.creator_id == a.id
    assert set(await svc.get_member_ids(session, conv.id)) == {a.id, b.id, c.id}


async def test_mark_read_and_counts(session):
    a = await _user(session, "a@x.com")
    b = await _user(session, "b@x.com")
    conv = await svc.get_or_create_direct_conversation(session, a.id, b.id)
    m = Message(conversation_id=conv.id, sender_id=a.id, content="hi")
    session.add(m)
    await session.flush()
    # b 尚未讀 → b 的未讀=1、read_count=0
    assert await svc.unread_count(session, conv.id, b.id) == 1
    assert await svc.read_count(session, m.id) == 0
    # b 讀了 → 回傳該則、未讀=0、read_count=1
    marked = await svc.mark_read(session, conv.id, b.id)
    assert marked == [m.id]
    assert await svc.unread_count(session, conv.id, b.id) == 0
    assert await svc.read_count(session, m.id) == 1
    # 重複 mark_read 不重複建立
    assert await svc.mark_read(session, conv.id, b.id) == []
