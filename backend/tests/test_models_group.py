import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import Conversation, ConversationMember, Message, MessageRead, User


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'m.db'}", poolclass=NullPool
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


pytestmark = pytest.mark.asyncio


async def test_group_conversation_with_members_and_reads(session):
    u1 = User(email="a@x.com", display_name="A", password_hash="h")
    u2 = User(email="b@x.com", display_name="B", password_hash="h")
    session.add_all([u1, u2])
    await session.flush()

    conv = Conversation(type="group", name="家族群", creator_id=u1.id)
    session.add(conv)
    await session.flush()
    session.add_all([
        ConversationMember(conversation_id=conv.id, user_id=u1.id),
        ConversationMember(conversation_id=conv.id, user_id=u2.id),
    ])
    msg = Message(conversation_id=conv.id, sender_id=u1.id, content="hi")
    session.add(msg)
    await session.flush()
    session.add(MessageRead(message_id=msg.id, user_id=u2.id))
    await session.commit()

    members = (await session.execute(
        select(ConversationMember).where(ConversationMember.conversation_id == conv.id)
    )).scalars().all()
    assert len(members) == 2
    reads = (await session.execute(
        select(MessageRead).where(MessageRead.message_id == msg.id)
    )).scalars().all()
    assert len(reads) == 1
    assert conv.type == "group" and conv.name == "家族群"
