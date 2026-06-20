import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import Conversation, Message, Reaction, User
from app.reactions import QUICK_REACTIONS


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'r.db'}", poolclass=NullPool
    )
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


pytestmark = pytest.mark.asyncio


def test_quick_reactions_whitelist():
    assert QUICK_REACTIONS == ["👍", "❤️", "😂", "😮", "😢", "🙏"]


async def test_reaction_unique_per_user_emoji(session):
    u = User(email="a@x.com", display_name="A", password_hash="h")
    session.add(u)
    await session.flush()
    conv = Conversation(type="direct", direct_key="k")
    session.add(conv)
    await session.flush()
    m = Message(conversation_id=conv.id, sender_id=u.id, content="hi")
    session.add(m)
    await session.flush()

    session.add(Reaction(message_id=m.id, user_id=u.id, emoji="👍"))
    await session.commit()
    session.add(Reaction(message_id=m.id, user_id=u.id, emoji="👍"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    # 不同 emoji 可共存
    session.add(Reaction(message_id=m.id, user_id=u.id, emoji="❤️"))
    await session.commit()
    rows = (await session.execute(select(Reaction).where(Reaction.message_id == m.id))).scalars().all()
    assert len(rows) == 2


async def test_message_has_edited_and_deleted_columns(session):
    u = User(email="b@x.com", display_name="B", password_hash="h")
    session.add(u)
    await session.flush()
    conv = Conversation(type="direct", direct_key="k2")
    session.add(conv)
    await session.flush()
    m = Message(conversation_id=conv.id, sender_id=u.id, content="hi")
    session.add(m)
    await session.commit()
    assert m.edited_at is None and m.deleted_at is None
