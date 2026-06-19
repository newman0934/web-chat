# 群組聊天 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在現有 1對1 MVP 上新增最小可用群組聊天，採統一資料模型（1對1 與群組共用一組表）。

**Architecture:** `Conversation` 一般化為「N 人對話」，成員存於 `ConversationMember`；已讀改用 `MessageRead`（支援群組「已讀 N」）。WS 推播改為「查成員 → 逐一推在線者」一條路徑。前端在 chat remote 加建群面板與群組顯示。

**Tech Stack:** FastAPI、SQLAlchemy 2.0（async）、Alembic、React 18 + Vite + Module Federation、pytest、Vitest。

**設計來源：** [docs/superpowers/specs/2026-06-19-group-chat-design.md](../specs/2026-06-19-group-chat-design.md)

## Global Constraints

- 後端測試以 venv 執行：`backend/.venv/Scripts/python.exe -m pytest`（PATH 上的 `python` 不可用）。
- UUID 主鍵一律用 SQLAlchemy 通用 `Uuid` 型別（非 `postgresql.UUID`）。
- 密碼 hash 維持 bcrypt 直呼，勿引入 passlib。
- WS 端點維持用 `db_module.SessionLocal()`（延遲引用），不可改走 `get_db` 依賴。
- 後端測試 DB 用檔案型 SQLite + `NullPool`（見 `backend/tests/conftest.py`），不可改回 in-memory + StaticPool。
- 前端 remote 改動後需 `npm run build` 才會反映到 host（dev 不產 `remoteEntry.js`）。
- 契約集中於 [frontend/contracts/index.ts](../../../frontend/contracts/index.ts)，shell↔remote 邊界改動需同步該檔。
- 每個 Task 結束都要 `tsc --noEmit` / `pytest` 綠燈後再 commit。

---

### Task 1: 資料模型（統一對話 + 成員 + 已讀）

**Files:**
- Modify: `backend/app/models/conversation.py`（加 type/name/creator_id/direct_key，移除 user_a_id/user_b_id 與 UNIQUE）
- Create: `backend/app/models/conversation_member.py`
- Create: `backend/app/models/message_read.py`
- Modify: `backend/app/models/message.py`（移除 read_at）
- Modify: `backend/app/models/__init__.py`（匯出新 model）
- Test: `backend/tests/test_models_group.py`

**Interfaces:**
- Produces:
  - `Conversation(id, type: str, name: str|None, creator_id: uuid|None, direct_key: str|None, created_at)`
  - `ConversationMember(id, conversation_id, user_id, created_at)`，UNIQUE(conversation_id, user_id)
  - `MessageRead(id, message_id, user_id, read_at)`，UNIQUE(message_id, user_id)
  - `Message(id, conversation_id, sender_id, content, created_at)`（無 read_at）

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_models_group.py`

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_models_group.py -v`
Expected: FAIL（`ImportError: cannot import name 'ConversationMember'` 等）

- [ ] **Step 3: 改 `conversation.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Conversation(Base):
    """1對1（type='direct'，2 成員）或群組（type='group'，N 成員）對話。"""

    __tablename__ = "conversations"
    __table_args__ = (
        # direct 對話以正規化的 direct_key 保證同兩人唯一；group 的 direct_key 為 NULL。
        UniqueConstraint("direct_key", name="uq_conversation_direct_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    direct_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 4: 建 `conversation_member.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConversationMember(Base):
    """對話成員。direct=2 筆、group=N 筆。"""

    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conv_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 5: 建 `message_read.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessageRead(Base):
    """已讀紀錄：某人讀過某則訊息。群組「已讀 N」與未讀數皆由此推導。"""

    __tablename__ = "message_reads"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_read"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 6: 改 `message.py`** — 移除 `read_at` 欄位（連同 import 中未用的型別）。保留 id/conversation_id/sender_id/content/created_at。

- [ ] **Step 7: 改 `models/__init__.py`**

```python
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.message import Message
from app.models.message_read import MessageRead
from app.models.user import User

__all__ = [
    "User", "Contact", "Conversation", "ConversationMember", "Message", "MessageRead",
]
```

- [ ] **Step 8: 跑測試確認通過**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_models_group.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/tests/test_models_group.py
git commit -m "feat(group): 統一對話資料模型 + 成員/已讀表"
```

---

### Task 2: 對話服務層（direct_key / 建群 / 成員 / 已讀）

**Files:**
- Modify: `backend/app/services/conversations.py`
- Test: `backend/tests/test_services_conversations.py`

**Interfaces:**
- Consumes: Task 1 的 models。
- Produces（全為 `app.services.conversations` 函式）：
  - `direct_key(a: uuid.UUID, b: uuid.UUID) -> str`
  - `async get_or_create_direct_conversation(db, u1, u2) -> Conversation`
  - `async create_group_conversation(db, creator_id, name, member_ids: list[uuid.UUID]) -> Conversation`
  - `async get_conversation_for_member(db, conversation_id, user_id) -> Conversation | None`
  - `async get_member_ids(db, conversation_id) -> list[uuid.UUID]`
  - `async get_other_member_ids(db, conversation_id, user_id) -> list[uuid.UUID]`
  - `async mark_read(db, conversation_id, user_id) -> list[uuid.UUID]`（回新標記已讀的 message_ids）
  - `async read_count(db, message_id) -> int`
  - `async unread_count(db, conversation_id, user_id) -> int`

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_services_conversations.py`

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_services_conversations.py -v`
Expected: FAIL（`AttributeError: module ... has no attribute 'direct_key'`）

- [ ] **Step 3: 改寫 `services/conversations.py`**

```python
"""對話相關共用邏輯，REST router 與 WebSocket 端點都依賴這裡。

統一模型：direct（2 成員）與 group（N 成員）共用 Conversation/ConversationMember。
direct 用正規化的 direct_key 保證同兩人唯一。
"""

import uuid

from sqlalchemy import and_, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationMember, Message, MessageRead


def direct_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """兩個 user_id 排序後組成穩定字串，作為 direct 對話唯一鍵。"""
    x, y = sorted([str(a), str(b)])
    return f"{x}:{y}"


async def get_member_ids(db: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == conversation_id
        )
    )
    return list(rows.scalars().all())


async def get_other_member_ids(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> list[uuid.UUID]:
    return [uid for uid in await get_member_ids(db, conversation_id) if uid != user_id]


async def get_or_create_direct_conversation(
    db: AsyncSession, u1: uuid.UUID, u2: uuid.UUID
) -> Conversation:
    key = direct_key(u1, u2)
    existing = await db.execute(
        select(Conversation).where(Conversation.direct_key == key)
    )
    conv = existing.scalar_one_or_none()
    if conv is not None:
        return conv
    conv = Conversation(type="direct", direct_key=key)
    db.add(conv)
    await db.flush()
    db.add_all([
        ConversationMember(conversation_id=conv.id, user_id=u1),
        ConversationMember(conversation_id=conv.id, user_id=u2),
    ])
    await db.flush()
    return conv


async def create_group_conversation(
    db: AsyncSession, creator_id: uuid.UUID, name: str, member_ids: list[uuid.UUID]
) -> Conversation:
    conv = Conversation(type="group", name=name, creator_id=creator_id)
    db.add(conv)
    await db.flush()
    # 建立者 + 受邀成員（去重）
    all_ids = {creator_id, *member_ids}
    db.add_all([
        ConversationMember(conversation_id=conv.id, user_id=uid) for uid in all_ids
    ])
    await db.flush()
    return conv


async def get_conversation_for_member(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> Conversation | None:
    """取得對話，且確認 user 是成員；否則 None。"""
    result = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(
            Conversation.id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def read_count(db: AsyncSession, message_id: uuid.UUID) -> int:
    """讀過此則的人數（MessageRead 不含寄件人，因 mark_read 只標記非自己訊息）。"""
    result = await db.execute(
        select(func.count()).select_from(MessageRead).where(
            MessageRead.message_id == message_id
        )
    )
    return result.scalar_one()


async def unread_count(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    read_subq = select(MessageRead.message_id).where(MessageRead.user_id == user_id)
    result = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            not_(Message.id.in_(read_subq)),
        )
    )
    return result.scalar_one()


async def mark_read(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> list[uuid.UUID]:
    """把此對話中 user 尚未讀、且非自己送出的訊息標記已讀，回傳新標記的 message_ids。"""
    read_subq = select(MessageRead.message_id).where(MessageRead.user_id == user_id)
    rows = await db.execute(
        select(Message.id).where(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id,
            not_(Message.id.in_(read_subq)),
        )
    )
    ids = list(rows.scalars().all())
    db.add_all([MessageRead(message_id=mid, user_id=user_id) for mid in ids])
    await db.flush()
    return ids
```

- [ ] **Step 4: 跑測試確認通過**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_services_conversations.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversations.py backend/tests/test_services_conversations.py
git commit -m "feat(group): 對話服務層 direct_key/建群/成員/已讀"
```

---

### Task 3: Schemas 與 REST（清單外型、建群、已讀數）

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/conversations.py`
- Modify: `backend/app/routers/contacts.py`（加好友改呼叫 `get_or_create_direct_conversation`）
- Test: `backend/tests/test_groups_rest.py`、更新 `backend/tests/test_conversations.py`、`backend/tests/test_contacts.py`

**Interfaces:**
- Consumes: Task 2 服務函式。
- Produces:
  - `GroupCreateRequest { name: str(min_length=1), member_user_ids: list[uuid.UUID] }`
  - `ConversationOut { id, type, name|None, other_user: UserOut|None, members: list[UserOut], last_message: MessageOut|None, unread_count: int }`
  - `MessageOut { id, conversation_id, sender_id, content, created_at, read_count: int }`（移除 read_at）
  - `POST /conversations/groups -> ConversationOut`（201）

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_groups_rest.py`

```python
import pytest

pytestmark = pytest.mark.asyncio


async def _uid(client, headers):
    return (await client.get("/users/me", headers=headers)).json()["id"]


async def test_create_group_with_friends(client, register_user, auth_headers):
    alice = await register_user("ga@example.com", "Alice")
    await register_user("gb@example.com", "Bob")
    await register_user("gc@example.com", "Cara")
    # 先互加好友
    await client.post("/contacts", json={"email": "gb@example.com"}, headers=auth_headers(alice))
    await client.post("/contacts", json={"email": "gc@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    member_ids = [c["user_id"] for c in contacts]

    resp = await client.post(
        "/conversations/groups",
        json={"name": "三人組", "member_user_ids": member_ids},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["type"] == "group"
    assert data["name"] == "三人組"
    assert len(data["members"]) == 3  # alice + 2


async def test_create_group_rejects_non_friend(client, register_user, auth_headers):
    alice = await register_user("gx@example.com", "Alice")
    bob = await register_user("gy@example.com", "Bob")  # 沒加好友
    bob_id = await _uid(client, auth_headers(bob))
    resp = await client.post(
        "/conversations/groups",
        json={"name": "x", "member_user_ids": [bob_id]},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 400


async def test_create_group_empty_name_422(client, register_user, auth_headers):
    alice = await register_user("gz@example.com", "Alice")
    resp = await client.post(
        "/conversations/groups",
        json={"name": "", "member_user_ids": []},
        headers=auth_headers(alice),
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_groups_rest.py -v`
Expected: FAIL（404，路由尚未存在）

- [ ] **Step 3: 改 `schemas.py`**

替換 `MessageOut`、`ConversationOut`，新增 `GroupCreateRequest`：

```python
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    created_at: datetime
    read_count: int = 0  # 讀過此則的人數（排除寄件人）


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_user_ids: list[uuid.UUID] = Field(default_factory=list)


class ConversationOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str | None = None
    other_user: UserOut | None = None  # direct 才有
    members: list[UserOut] = Field(default_factory=list)
    last_message: MessageOut | None = None
    unread_count: int = 0
```

- [ ] **Step 4: 改 `routers/conversations.py`**

清單與訊息改用新服務 + 組裝 members/read_count。完整檔：

```python
"""對話清單、建群與歷史訊息（分頁）。"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Contact, Conversation, ConversationMember, Message, User
from app.schemas import ConversationOut, GroupCreateRequest, MessageOut, UserOut
from app.services.conversations import (
    create_group_conversation,
    get_conversation_for_member,
    get_member_ids,
    read_count,
    unread_count,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _build_conversation_out(
    db: AsyncSession, conv: Conversation, me: User
) -> ConversationOut:
    member_ids = await get_member_ids(db, conv.id)
    members = [await db.get(User, uid) for uid in member_ids]
    other = None
    if conv.type == "direct":
        other = next((u for u in members if u.id != me.id), None)

    last_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last = last_res.scalar_one_or_none()
    last_out = None
    if last is not None:
        last_out = MessageOut(
            id=last.id, conversation_id=last.conversation_id, sender_id=last.sender_id,
            content=last.content, created_at=last.created_at,
            read_count=await read_count(db, last.id),
        )

    return ConversationOut(
        id=conv.id,
        type=conv.type,
        name=conv.name,
        other_user=UserOut.model_validate(other) if other else None,
        members=[UserOut.model_validate(u) for u in members],
        last_message=last_out,
        unread_count=await unread_count(db, conv.id, me.id),
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(ConversationMember.user_id == current_user.id)
    )
    conversations = rows.scalars().all()
    out = [await _build_conversation_out(db, c, current_user) for c in conversations]
    out.sort(
        key=lambda c: c.last_message.created_at if c.last_message else datetime.min,
        reverse=True,
    )
    return out


@router.post("/groups", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member_ids = [uid for uid in dict.fromkeys(payload.member_user_ids) if uid != current_user.id]
    if not member_ids:
        raise HTTPException(status_code=400, detail="群組至少要有一位其他成員")
    # 每位成員都必須是好友
    friend_rows = await db.execute(
        select(Contact.contact_user_id).where(Contact.user_id == current_user.id)
    )
    friend_ids = set(friend_rows.scalars().all())
    if any(uid not in friend_ids for uid in member_ids):
        raise HTTPException(status_code=400, detail="只能把好友加入群組")

    conv = await create_group_conversation(db, current_user.id, payload.name, member_ids)
    await db.commit()
    await db.refresh(conv)
    return await _build_conversation_out(db, conv, current_user)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_for_member(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")

    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()
    return [
        MessageOut(
            id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
            content=m.content, created_at=m.created_at,
            read_count=await read_count(db, m.id),
        )
        for m in messages
    ]
```

- [ ] **Step 5: 改 `routers/contacts.py`** — 把兩處 `get_or_create_conversation(...)` 改名為 `get_or_create_direct_conversation(...)`，import 同步改。其餘不動。

- [ ] **Step 6: 更新既有測試** — `backend/tests/test_conversations.py`：把建立訊息後對 `read_at` 的斷言改為 `read_count`。例如「未讀」案例：Bob 傳 2 則後 Alice 端 `unread_count == 2`、`last_message.content == "there"`；新增「Alice 讀後」改以 `read_count` 驗證（若原測試有讀取斷言）。`test_messages_forbidden_for_outsider` 維持 404（outsider 非成員）。

> 注意：`test_conversations.py` 直接 `Message(...)` 寫入時不要再帶 `read_at`（欄位已移除）。

- [ ] **Step 7: 跑全部後端測試**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS（含新 test_groups_rest.py 與更新後的既有測試）

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas.py backend/app/routers backend/tests
git commit -m "feat(group): 建群 REST 與對話清單/已讀數外型"
```

---

### Task 4: WebSocket（群組廣播 + 已讀 message_ids）

**Files:**
- Modify: `backend/app/ws/router.py`
- Test: `backend/tests/test_ws.py`（更新 + 新增群組案例）

**Interfaces:**
- Consumes: Task 2 服務（`get_conversation_for_member`、`get_other_member_ids`、`mark_read`、`read_count`）。
- Produces（WS 行為）：
  - 送訊息：推給「所有其他在線成員」。
  - 已讀：Server→Client `read` 事件 payload 改為 `{type:"read", conversation_id, reader_id, message_ids:[...]}`。
  - `message`/`ack` 的 `message` 物件新增 `read_count`（送出當下為 0）。

- [ ] **Step 1: 改 `ws/router.py` 的序列化與 import**

`_serialize_message` 改為帶 `read_count`（剛送出為 0，省一次查詢）：

```python
def _serialize_message(msg: Message, read_count: int = 0) -> dict:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": msg.content,
        "created_at": msg.created_at.astimezone(timezone.utc).isoformat(),
        "read_count": read_count,
    }
```

import 改用：`from app.services.conversations import get_conversation_for_member, get_other_member_ids, mark_read`。

- [ ] **Step 2: 改 `_handle_send`** — 驗成員、寫訊息、ACK、廣播給其他成員：

```python
    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json(
                {"type": "error", "reason": "forbidden", "temp_id": temp_id}
            )
            return
        message = Message(conversation_id=conv_id, sender_id=user.id, content=content)
        db.add(message)
        try:
            await db.commit()
            await db.refresh(message)
        except Exception:
            await db.rollback()
            await websocket.send_json(
                {"type": "error", "reason": "db_error", "temp_id": temp_id}
            )
            return
        payload = _serialize_message(message)
        recipients = await get_other_member_ids(db, conv_id, user.id)

    await websocket.send_json({"type": "ack", "temp_id": temp_id, "message": payload})
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})
```

- [ ] **Step 3: 改 `_handle_read`** — 用服務 `mark_read`，廣播帶 `message_ids`：

```python
    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        marked = await mark_read(db, conv_id, user.id)
        await db.commit()
        recipients = await get_other_member_ids(db, conv_id, user.id)

    if not marked:
        return
    message_ids = [str(mid) for mid in marked]
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {
                "type": "read",
                "conversation_id": str(conv_id),
                "reader_id": str(user.id),
                "message_ids": message_ids,
            })
```

`_handle_typing` 同樣把 `get_conversation_for_user` 改成 `get_conversation_for_member`、收件人改用 `get_other_member_ids`（廣播給其他成員）。

- [ ] **Step 4: 更新/新增 WS 測試** — `backend/tests/test_ws.py`

更新既有：`test_ws_message_ack_and_push_and_persist` 的 ack/pushed message 斷言加 `assert ack["message"]["read_count"] == 0`。新增群組廣播測試：

```python
async def test_ws_group_broadcast_to_all_members(client, register_user, auth_headers):
    alice = await register_user("wga@example.com", "Alice")
    bob = await register_user("wgb@example.com", "Bob")
    cara = await register_user("wgc@example.com", "Cara")
    await client.post("/contacts", json={"email": "wgb@example.com"}, headers=auth_headers(alice))
    await client.post("/contacts", json={"email": "wgc@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    member_ids = [c["user_id"] for c in contacts]
    conv = (await client.post(
        "/conversations/groups",
        json={"name": "G", "member_user_ids": member_ids},
        headers=auth_headers(alice),
    )).json()
    conv_id = conv["id"]

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb, \
             tc.websocket_connect(f"/ws?token={cara}") as wc, \
             tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "message", "conversation_id": conv_id,
                          "content": "hi all", "temp_id": "t1"})
            assert wa.receive_json()["type"] == "ack"
            assert wb.receive_json()["message"]["content"] == "hi all"
            assert wc.receive_json()["message"]["content"] == "hi all"


async def test_ws_group_read_broadcasts_message_ids(client, register_user, auth_headers):
    alice = await register_user("wra@example.com", "Alice")
    bob = await register_user("wrb@example.com", "Bob")
    await client.post("/contacts", json={"email": "wrb@example.com"}, headers=auth_headers(alice))
    contacts = (await client.get("/contacts", headers=auth_headers(alice))).json()
    conv = (await client.post(
        "/conversations/groups",
        json={"name": "G2", "member_user_ids": [contacts[0]["user_id"]]},
        headers=auth_headers(alice),
    )).json()
    conv_id = conv["id"]

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "message", "conversation_id": conv_id,
                          "content": "ping", "temp_id": "t"})
            wa.receive_json()  # ack
            wb.receive_json()  # message push
            wb.send_json({"type": "read", "conversation_id": conv_id})
            evt = wa.receive_json()
            assert evt["type"] == "read"
            assert evt["reader_id"]
            assert len(evt["message_ids"]) == 1
```

- [ ] **Step 5: 跑全部後端測試**

Run: `backend/.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/ws/router.py backend/tests/test_ws.py
git commit -m "feat(group): WS 群組廣播與已讀 message_ids"
```

---

### Task 5: Alembic 遷移 0002（含資料搬移、SQLite 批次模式）

**Files:**
- Create: `backend/alembic/versions/0002_group_chat.py`
- Test: 手動驗證指令（升級 + 查表）

**Interfaces:**
- Consumes: Task 1~4 的 schema。
- Produces: 可從 0001 升到 0002 的遷移，保留既有 1對1 資料。

- [ ] **Step 1: 寫遷移** — `backend/alembic/versions/0002_group_chat.py`

```python
"""group chat: unified conversations, members, message reads

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 新欄位（先可為 NULL，搬移後再視需要約束）
    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("type", sa.String(16), nullable=False, server_default="direct"))
        b.add_column(sa.Column("name", sa.String(100), nullable=True))
        b.add_column(sa.Column("creator_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("direct_key", sa.String(80), nullable=True))

    # 2) 新表
    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conv_member"),
    )
    op.create_index(op.f("ix_conversation_members_conversation_id"), "conversation_members", ["conversation_id"])
    op.create_index(op.f("ix_conversation_members_user_id"), "conversation_members", ["user_id"])

    op.create_table(
        "message_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_read"),
    )
    op.create_index(op.f("ix_message_reads_message_id"), "message_reads", ["message_id"])

    # 3) 資料搬移
    conn = op.get_bind()
    convs = conn.execute(sa.text(
        "SELECT id, user_a_id, user_b_id FROM conversations"
    )).fetchall()
    for cid, a, b in convs:
        a_s, b_s = sorted([str(a), str(b)])
        conn.execute(
            sa.text("UPDATE conversations SET type='direct', direct_key=:k WHERE id=:i"),
            {"k": f"{a_s}:{b_s}", "i": cid},
        )
        for uid in (a, b):
            conn.execute(
                sa.text(
                    "INSERT INTO conversation_members (id, conversation_id, user_id) "
                    "VALUES (:id, :c, :u)"
                ),
                {"id": _uuid(), "c": cid, "u": uid},
            )
    # read_at → message_reads（reader = 非寄件人那位成員）
    msgs = conn.execute(sa.text(
        "SELECT m.id, m.conversation_id, m.sender_id, m.read_at, "
        "c.user_a_id, c.user_b_id FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.read_at IS NOT NULL"
    )).fetchall()
    for mid, _c, sender, read_at, a, b in msgs:
        reader = b if str(sender) == str(a) else a
        conn.execute(
            sa.text(
                "INSERT INTO message_reads (id, message_id, user_id, read_at) "
                "VALUES (:id, :m, :u, :r)"
            ),
            {"id": _uuid(), "m": mid, "u": reader, "r": read_at},
        )

    # 4) 移除舊欄位 / 約束
    with op.batch_alter_table("conversations") as b:
        b.drop_constraint("uq_conversation_pair", type_="unique")
        b.create_unique_constraint("uq_conversation_direct_key", ["direct_key"])
        b.drop_column("user_a_id")
        b.drop_column("user_b_id")
    with op.batch_alter_table("messages") as b:
        b.drop_column("read_at")


def downgrade() -> None:
    raise NotImplementedError("0002 為破壞性遷移，不提供 downgrade")


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())
```

> 註：搬移用原生 SQL 以避免依賴 ORM；`_uuid()` 產生字串型 UUID（SQLite 存 CHAR、Postgres 的 Uuid 欄位可接受字串）。

- [ ] **Step 2: 在乾淨 DB 驗證升級**

```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/_mig_check.db"
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('_mig_check.db'); print(sorted(r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")))"
rm backend/_mig_check.db
```
Expected: 輸出含 `conversation_members`、`message_reads`、`conversations`、`messages` 等表，指令 exit 0。

- [ ] **Step 3: 對既有 dev.db 升級（保留資料）**

```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/dev.db"
.venv/Scripts/python.exe -m alembic upgrade head
```
Expected: exit 0；舊的 Alice/Bob direct 對話應出現於 `conversation_members`。

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0002_group_chat.py
git commit -m "feat(group): Alembic 0002 統一對話遷移與資料搬移"
```

---

### Task 6: 前端契約 + messageStore（read_count / read 事件）

**Files:**
- Modify: `frontend/contracts/index.ts`
- Modify: `frontend/chat/src/messageStore.ts`
- Test: `frontend/chat/src/messageStore.test.ts`（更新 + 新增）

**Interfaces:**
- Produces:
  - `Conversation` 加 `type: 'direct'|'group'`、`name: string|null`、`members: CurrentUser[]`；`other_user: CurrentUser | null`。
  - `Message.read_at` → `read_count: number`。
  - `ServerWsMessage` 的 read 變 `{ type:'read'; conversation_id: string; reader_id: string; message_ids: string[] }`。
  - 新增 `GroupCreateRequest { name: string; member_user_ids: string[] }`。
  - messageStore 新增 `applyReadReceipt(list, messageIds): ChatMessage[]`（對應訊息 `read_count + 1`）；`ChatMessage` 改用 `read_count`。

- [ ] **Step 1: 改契約** — `frontend/contracts/index.ts`

```typescript
export interface Conversation {
  id: string;
  type: 'direct' | 'group';
  name: string | null;
  other_user: CurrentUser | null;
  members: CurrentUser[];
  last_message: Message | null;
  unread_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  created_at: string;
  read_count: number;
}

export interface GroupCreateRequest {
  name: string;
  member_user_ids: string[];
}
```
並把 `ServerWsMessage` 的 read 分支改為：
```typescript
  | { type: 'read'; conversation_id: string; reader_id: string; message_ids: string[] }
```

- [ ] **Step 2: 更新 messageStore 測試** — `frontend/chat/src/messageStore.test.ts`

把 `realMessage` 的 `read_at: null` 改成 `read_count: 0`；新增：

```typescript
import { applyReadReceipt } from './messageStore';

it('applyReadReceipt 對指定訊息 read_count +1', () => {
  const list = fromHistory([realMessage('m1', 'a'), realMessage('m2', 'b')]);
  const next = applyReadReceipt(list, ['m1']);
  expect(next.find((m) => m.id === 'm1')!.read_count).toBe(1);
  expect(next.find((m) => m.id === 'm2')!.read_count).toBe(0);
});
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts`
Expected: FAIL（`applyReadReceipt` 未定義、`read_at` 型別錯）

- [ ] **Step 4: 改 `messageStore.ts`**

`ChatMessage` 改用 `read_count`（移除 read_at 相關）；`makeOptimistic` 設 `read_count: 0`；新增：

```typescript
/** 收到 read 事件：把被讀到的訊息 read_count + 1（用於「已讀 N」/「已讀」）。 */
export function applyReadReceipt(
  list: ChatMessage[],
  messageIds: string[],
): ChatMessage[] {
  const ids = new Set(messageIds);
  return list.map((m) =>
    ids.has(m.id) ? { ...m, read_count: m.read_count + 1 } : m,
  );
}
```

> `makeOptimistic` 回傳物件把 `read_at: null` 改為 `read_count: 0`；其餘函式（addOptimistic/reconcileAck/...）型別隨之自動相容。

- [ ] **Step 5: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/contracts/index.ts frontend/chat/src/messageStore.ts frontend/chat/src/messageStore.test.ts
git commit -m "feat(group): 契約與 messageStore 改用 read_count + read 收據"
```

---

### Task 7: chat API + Sidebar（群組顯示 + 建群面板）

**Files:**
- Modify: `frontend/chat/src/api.ts`
- Modify: `frontend/chat/src/components/Sidebar.tsx`
- Test: `frontend/chat/src/components/Sidebar.test.tsx`（新增）

**Interfaces:**
- Consumes: Task 6 契約。
- Produces:
  - `ApiClient.createGroup(name: string, memberUserIds: string[]): Promise<Conversation>`
  - Sidebar 新增 props：`contacts: Contact[]`、`onCreateGroup(name, memberIds): Promise<string|null>`。

- [ ] **Step 1: 改 `api.ts`** — 新增方法：

```typescript
import type { Contact, Conversation, GroupCreateRequest, Message } from '../../contracts';

// ... 在 class 內：
  createGroup(name: string, memberUserIds: string[]) {
    const body: GroupCreateRequest = { name, member_user_ids: memberUserIds };
    return this.req<Conversation>('/conversations/groups', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }
```

- [ ] **Step 2: 寫 Sidebar 測試** — `frontend/chat/src/components/Sidebar.test.tsx`

```typescript
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Conversation } from '../../../contracts';
import { Sidebar } from './Sidebar';

const groupConv: Conversation = {
  id: 'g1', type: 'group', name: '家族群', other_user: null,
  members: [
    { id: 'u1', email: 'a@x.com', display_name: 'A' },
    { id: 'u2', email: 'b@x.com', display_name: 'B' },
    { id: 'u3', email: 'c@x.com', display_name: 'C' },
  ],
  last_message: null, unread_count: 0,
};

function renderSidebar(over = {}) {
  return render(
    <Sidebar
      conversations={[groupConv]} activeId={null} currentUserName="A"
      socketStatus="open" contacts={[]}
      onSelect={vi.fn()} onAddContact={vi.fn()} onCreateGroup={vi.fn()} onLogout={vi.fn()}
      {...over}
    />,
  );
}

describe('Sidebar 群組', () => {
  it('群組顯示名稱與成員數', () => {
    renderSidebar();
    expect(screen.getByText('家族群')).toBeInTheDocument();
    expect(screen.getByText(/3 人/)).toBeInTheDocument();
  });

  it('點新群組展開建群面板', () => {
    renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: /新群組/ }));
    expect(screen.getByLabelText('群組名稱')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/Sidebar.test.tsx`
Expected: FAIL（Sidebar 尚未接受 contacts/onCreateGroup、無新群組按鈕）

- [ ] **Step 4: 改 `Sidebar.tsx`** — 加入 props 與建群面板。新增/調整：

```typescript
// props 介面加：
//   contacts: Contact[];
//   onCreateGroup: (name: string, memberIds: string[]) => Promise<string | null>;
// 內部 state：
//   const [showGroup, setShowGroup] = useState(false);
//   const [groupName, setGroupName] = useState('');
//   const [picked, setPicked] = useState<Set<string>>(new Set());
//   const [groupErr, setGroupErr] = useState<string | null>(null);
```

清單項目顯示改為：

```tsx
<span className="block truncate font-medium text-slate-800">
  {c.type === 'group' ? c.name : c.other_user?.display_name}
  {c.type === 'group' && (
    <span className="ml-1 text-xs text-slate-400">· {c.members.length} 人</span>
  )}
</span>
```

在加好友表單下方加「＋ 新群組」按鈕與面板（勾選好友 + 命名 + 建立），submit 呼叫 `onCreateGroup(groupName, [...picked])`，成功（回 null）則收合並清空，失敗顯示 `groupErr`。面板輸入框需 `aria-label="群組名稱"`。

- [ ] **Step 5: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/Sidebar.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/chat/src/api.ts frontend/chat/src/components/Sidebar.tsx frontend/chat/src/components/Sidebar.test.tsx
git commit -m "feat(group): chat API createGroup 與 Sidebar 建群面板"
```

---

### Task 8: Thread（群組寄件人名字 + 已讀 N）

**Files:**
- Modify: `frontend/chat/src/components/Thread.tsx`
- Test: `frontend/chat/src/components/Thread.test.tsx`（更新 + 新增）

**Interfaces:**
- Consumes: Task 6 的 `ChatMessage`（含 `read_count`）。
- Produces: `Thread` 新增 props：`isGroup: boolean`、`memberNames: Record<string, string>`（sender_id → display_name）。

- [ ] **Step 1: 更新測試** — `frontend/chat/src/components/Thread.test.tsx`

`msg(...)` 的 `read_at: null` 改 `read_count: 0`；既有 render 呼叫補上 `isGroup={false}` 與 `memberNames={{}}`。新增：

```typescript
it('群組顯示寄件人名字與已讀 N', () => {
  render(
    <Thread
      title="家族群" isGroup memberNames={{ u2: 'Bob' }}
      messages={[
        msg({ id: 'm1', sender_id: 'u2', content: '嗨' }),               // 別人 → 顯示名字
        msg({ id: 'm2', sender_id: 'me', content: '哈', read_count: 2 }), // 自己 → 已讀 2
      ]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
    />,
  );
  expect(screen.getByText('Bob')).toBeInTheDocument();
  expect(screen.getByText('已讀 2')).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: FAIL（Thread 不接受 isGroup/memberNames；無「已讀 N」）

- [ ] **Step 3: 改 `Thread.tsx`**

`ThreadProps` 加 `isGroup: boolean`、`memberNames: Record<string,string>`，傳給 `MessageBubble`。`MessageBubble` 調整：

```tsx
function MessageBubble({ message, mine, isGroup, senderName, onRetry }: {
  message: ChatMessage; mine: boolean; isGroup: boolean;
  senderName?: string; onRetry: (tempId: string) => void;
}) {
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[70%] rounded-2xl px-4 py-2 ${mine ? 'bg-indigo-600 text-white' : 'bg-white text-slate-800 shadow'}`}>
        {isGroup && !mine && senderName && (
          <p className="mb-0.5 text-xs font-medium text-indigo-500">{senderName}</p>
        )}
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {mine && (
          <p className="mt-1 text-right text-xs opacity-80">
            {message.status === 'sending' && '傳送中…'}
            {message.status === 'sent' && (
              isGroup
                ? (message.read_count > 0 ? `已讀 ${message.read_count}` : '已送出')
                : (message.read_count > 0 ? '已讀' : '已送出')
            )}
            {message.status === 'failed' && (
              <button onClick={() => message.temp_id && onRetry(message.temp_id)} className="underline">
                未送出，點擊重試
              </button>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
```

在 map 處傳 `isGroup={isGroup}` 與 `senderName={memberNames[m.sender_id]}`。

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/components/Thread.tsx frontend/chat/src/components/Thread.test.tsx
git commit -m "feat(group): Thread 群組寄件人名字與已讀 N"
```

---

### Task 9: ChatApp 串接（建群、read 收據、群組 props）

**Files:**
- Modify: `frontend/chat/src/ChatApp.tsx`
- Test: 以 `tsc --noEmit` + 既有/前述測試全綠 + 手動驗證

**Interfaces:**
- Consumes: Task 6~8（api.createGroup、applyReadReceipt、Sidebar/Thread 新 props）。

- [ ] **Step 1: 改 read 事件處理** — `handleServerMessage` 的 `case 'read'` 改用 `applyReadReceipt`：

```typescript
case 'read': {
  setMessages((prev) => {
    const list = prev[msg.conversation_id];
    if (!list) return prev;
    return {
      ...prev,
      [msg.conversation_id]: applyReadReceipt(list, msg.message_ids),
    };
  });
  break;
}
```
（移除原本依 `read_at` 標記的邏輯；import 補 `applyReadReceipt`，移除未用的 import。）

- [ ] **Step 2: 載入好友清單** — 加 state `const [contacts, setContacts] = useState<Contact[]>([]);`，在初始 effect 內 `setContacts(await api.listContacts())`（與 loadConversations 並行）。import `Contact` 型別與 `api.listContacts`。

- [ ] **Step 3: 建群處理** — 新增：

```typescript
const createGroup = useCallback(
  async (name: string, memberIds: string[]): Promise<string | null> => {
    try {
      const conv = await api.createGroup(name, memberIds);
      await loadConversations();
      setActiveId(conv.id);
      return null;
    } catch (err) {
      if (err instanceof UnauthorizedError) { onLogout(); return '憑證失效'; }
      if (err instanceof ApiError) return err.message;
      return '建立群組失敗';
    }
  },
  [api, loadConversations, onLogout],
);
```

- [ ] **Step 4: 傳 props 給 Sidebar/Thread** — Sidebar 加 `contacts={contacts}` 與 `onCreateGroup={createGroup}`；Thread 加：

```tsx
const activeConv = conversations.find((c) => c.id === activeId) ?? null;
const isGroup = activeConv?.type === 'group';
const memberNames = Object.fromEntries(
  (activeConv?.members ?? []).map((m) => [m.id, m.display_name]),
);
const title = activeConv
  ? (activeConv.type === 'group' ? activeConv.name ?? '群組' : activeConv.other_user?.display_name ?? '')
  : '';
// <Thread ... isGroup={isGroup} memberNames={memberNames} title={title} />
```

- [ ] **Step 5: typecheck + 全部前端測試**

Run:
```bash
cd frontend/chat && npx tsc --noEmit && npx vitest run
cd ../shell && npx tsc --noEmit
```
Expected: 全 PASS（chat 測試含 messageStore/Sidebar/Thread；shell typecheck 乾淨）

- [ ] **Step 6: Commit**

```bash
git add frontend/chat/src/ChatApp.tsx
git commit -m "feat(group): ChatApp 串接建群與 read 收據"
```

---

### Task 10: 端到端煙霧測試與文件更新

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md`（把群組從「明確不做」移到已實作，或加註）
- Modify: `progress.md`、`README.md`（群組啟動/使用說明）

- [ ] **Step 1: 啟動整套**（依 CLAUDE.md：backend SQLite、auth/chat build+preview、shell dev）

- [ ] **Step 2: 手動驗證** — 用三個帳號（瀏覽器 + 兩個無痕視窗）：Alice 建「三人組」群組 → 三人都看到 → Alice 送訊息，Bob/Cara 即時收到 → Bob/Cara 開啟後 Alice 看到「已讀 2」。截圖存 `docs/`。

- [ ] **Step 3: 更新文件** — spec 標註群組已實作；progress.md 更新現況與「已完成」；README 補群組說明。

- [ ] **Step 4: 全測試總跑**

Run:
```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
cd ../frontend/shell && npx vitest run && npx tsc --noEmit
cd ../auth && npx vitest run && npx tsc --noEmit
cd ../chat && npx vitest run && npx tsc --noEmit
```
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add docs progress.md README.md
git commit -m "docs(group): 群組聊天完成，更新設計/進度/README"
```

---

## Self-Review（計畫對照 spec）

- **Spec §3 資料模型** → Task 1（models）+ Task 5（migration）。✅
- **Spec §3 衍生計算（已讀 N／未讀／direct_key）** → Task 2（services）。✅
- **Spec §4 REST（清單外型、建群驗證、read_count）** → Task 3。✅
- **Spec §5 WS（廣播、read message_ids）** → Task 4。✅
- **Spec §6 前端（契約、messageStore、Sidebar、Thread、ChatApp）** → Task 6/7/8/9。✅
- **Spec §7 遷移（批次模式、資料搬移）** → Task 5。✅
- **Spec §8 測試** → 每個 Task 內含 TDD；Task 10 端到端。✅
- **回歸（1對1 不壞）** → Task 3 Step 6 更新既有測試、Task 4 更新 WS 測試、Task 10 總跑。✅

型別一致性檢查：`read_count`（後端 MessageOut / 前端 Message / ChatMessage）、`message_ids`（WS read 事件兩端）、`get_conversation_for_member`（services/REST/WS 一致命名）、`createGroup`/`create_group_conversation`/`POST /conversations/groups` 對齊。無未定義引用。

> 註：本計畫移除 `app/services/conversations.py` 舊的 `order_pair`/`get_or_create_conversation`/`get_conversation_for_user`/`other_user_id`。所有呼叫點（contacts router、conversations router、ws router）均已在對應 Task 改為新函式，無殘留引用。
