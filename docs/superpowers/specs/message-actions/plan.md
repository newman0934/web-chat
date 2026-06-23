# 訊息編輯 / 刪除 / 表情回應 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓使用者對既有訊息進行編輯、軟刪除與表情回應，皆走 WebSocket 並以單一 `message_updated` 事件即時廣播給對話成員。

**Architecture:** Client→Server 新增 `edit`/`delete`/`react`；Server→Client 用 `message_updated`（完整 MessageOut）廣播給該對話所有在線成員（含操作者）。重用既有 `get_conversation_for_member` 權限與群組廣播。reactions 形狀與觀看者無關（`{emoji, count, user_ids}`），前端自行判定「我按過沒」。

**Tech Stack:** FastAPI、SQLAlchemy 2.0 async、Alembic、React 18 + Vite + Module Federation + zustand、pytest、Vitest。

**設計來源：** [spec.md](spec.md)

## Global Constraints

- 後端測試以 venv 執行：`backend/.venv/Scripts/python.exe -m pytest`（PATH 的 `python` 是 Store stub，不可用）。
- 固定表情白名單：`["👍", "❤️", "😂", "😮", "😢", "🙏"]`，後端在 `app/reactions.py`、前端在 `frontend/contracts/index.ts` 各一份 `QUICK_REACTIONS`。
- 權限：編輯/刪除限 `message.sender_id == user`；表情限對話成員（`get_conversation_for_member`）。已刪除訊息不可編輯。
- 已刪除訊息所有輸出一律 `content=""`、`attachment=null`、`reactions=[]`。
- UUID 用通用 `Uuid`；WS 端點維持用 `db_module.SessionLocal()`（勿改 get_db）；密碼勿引入 passlib；測試 DB 用檔案型 SQLite + `NullPool`。
- 後端測試走 SQLite，conftest 用 `Base.metadata.create_all`（涵蓋新 model，不靠 migration）。
- 前端 remote 改動後需 `npm run build` 才反映到 host；契約集中於 `frontend/contracts/index.ts`。
- Commit 格式（CLAUDE.md）：`[feature][type][scope] description`，feature=`msg-actions`；結尾保留 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 每個 Task 結束都要相關測試 / `tsc --noEmit` 綠燈後再 commit。

---

### Task 1: 資料模型 + 遷移 + 表情白名單

**Files:**
- Modify: `backend/app/models/message.py`（加 `edited_at`、`deleted_at`）
- Create: `backend/app/models/reaction.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/reactions.py`（`QUICK_REACTIONS`）
- Create: `backend/alembic/versions/0004_message_actions.py`
- Test: `backend/tests/test_reaction_model.py`

**Interfaces:**
- Produces:
  - `Message.edited_at: datetime | None`、`Message.deleted_at: datetime | None`
  - `Reaction(id, message_id, user_id, emoji, created_at)`，UNIQUE(message_id, user_id, emoji)
  - `app.reactions.QUICK_REACTIONS: list[str]`

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_reaction_model.py`

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_reaction_model.py -v`
Expected: FAIL（`ImportError: cannot import name 'Reaction'` / `app.reactions`）

- [ ] **Step 3: 建 `app/reactions.py`**

```python
"""固定快速表情白名單（前端 frontend/contracts/index.ts 另有同份）。"""

QUICK_REACTIONS: list[str] = ["👍", "❤️", "😂", "😮", "😢", "🙏"]
```

- [ ] **Step 4: 改 `models/message.py`** — 在 `created_at` 之後加兩欄位：

```python
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 5: 建 `models/reaction.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Reaction(Base):
    """單一使用者對單一訊息的單一 emoji 反應。"""

    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_reaction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 6: 改 `models/__init__.py`** — 匯入並匯出 `Reaction`：

```python
from app.models.attachment import Attachment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.message import Message
from app.models.message_read import MessageRead
from app.models.reaction import Reaction
from app.models.user import User

__all__ = [
    "User", "Contact", "Conversation", "ConversationMember",
    "Message", "MessageRead", "Attachment", "Reaction",
]
```

- [ ] **Step 7: 建遷移 `0004_message_actions.py`**

```python
"""message edit/delete columns + reactions table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "reactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", "emoji", name="uq_reaction"),
    )
    op.create_index(op.f("ix_reactions_message_id"), "reactions", ["message_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_reactions_message_id"), table_name="reactions")
    op.drop_table("reactions")
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "edited_at")
```

- [ ] **Step 8: 跑測試確認通過 + 驗證遷移**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_reaction_model.py -v
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/_mig4.db"
.venv/Scripts/python.exe -m alembic upgrade head && rm _mig4.db
```
Expected: 測試 3 passed；alembic exit 0。

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/app/reactions.py backend/alembic/versions/0004_message_actions.py backend/tests/test_reaction_model.py
git commit -m "[msg-actions][feat][backend] Message edited/deleted 欄位 + Reaction 表 + 0004 遷移"
```

---

### Task 2: Schemas + reactions 聚合 + REST 歷史

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/services/conversations.py`（`get_reaction_groups`）
- Modify: `backend/app/routers/conversations.py`（`list_messages` 帶新欄位 + 遮蔽已刪）
- Test: `backend/tests/test_message_actions_rest.py`

**Interfaces:**
- Consumes: Task 1（`Reaction`、`Message.edited_at/deleted_at`）。
- Produces:
  - `ReactionGroupOut { emoji: str, count: int, user_ids: list[uuid.UUID] }`
  - `MessageOut` += `edited_at: datetime | None = None`、`deleted: bool = False`、`reactions: list[ReactionGroupOut] = []`
  - `app.services.conversations.get_reaction_groups(db, message_id) -> list[ReactionGroupOut]`（依 emoji 聚合，user_ids 為該 emoji 的反應者）

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_message_actions_rest.py`

```python
import uuid

import pytest

from app.models import Message, Reaction

pytestmark = pytest.mark.asyncio


async def _setup(client, register_user, auth_headers, session_factory):
    alice = await register_user("ma@example.com", "Alice")
    bob = await register_user("mb@example.com", "Bob")
    await client.post("/contacts", json={"email": "mb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="hi")
        s.add(m)
        await s.flush()
        s.add_all([
            Reaction(message_id=m.id, user_id=uuid.UUID(aid), emoji="👍"),
            Reaction(message_id=m.id, user_id=uuid.UUID(bid), emoji="👍"),
            Reaction(message_id=m.id, user_id=uuid.UUID(aid), emoji="❤️"),
        ])
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], aid, bid, mid


async def test_history_includes_reactions(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, aid, bid, mid = await _setup(client, register_user, auth_headers, session_factory)
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    reactions = {r["emoji"]: r for r in msgs[0]["reactions"]}
    assert reactions["👍"]["count"] == 2
    assert set(reactions["👍"]["user_ids"]) == {aid, bid}
    assert reactions["❤️"]["count"] == 1
    assert msgs[0]["edited_at"] is None
    assert msgs[0]["deleted"] is False


async def test_history_masks_deleted(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, aid, bid, mid = await _setup(client, register_user, auth_headers, session_factory)
    from datetime import datetime, timezone
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.deleted_at = datetime.now(timezone.utc)
        m.content = ""
        await s.commit()
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert msgs[0]["deleted"] is True
    assert msgs[0]["content"] == ""
    assert msgs[0]["reactions"] == []
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_message_actions_rest.py -v`
Expected: FAIL（`KeyError: 'reactions'`）

- [ ] **Step 3: 改 `schemas.py`** — 在 `MessageOut` 之前加 `ReactionGroupOut`，並擴充 `MessageOut`：

```python
class ReactionGroupOut(BaseModel):
    emoji: str
    count: int
    user_ids: list[uuid.UUID] = Field(default_factory=list)
```

在 `MessageOut` 內（`attachment` 之後）加：

```python
    edited_at: datetime | None = None
    deleted: bool = False
    reactions: list[ReactionGroupOut] = Field(default_factory=list)
```

- [ ] **Step 4: 加聚合輔助** — `backend/app/services/conversations.py` 末端：

```python
from app.models import Reaction  # 併入頂部既有 from app.models import ...
from app.schemas import ReactionGroupOut  # 置於檔案頂部 import 區


async def get_reaction_groups(
    db: AsyncSession, message_id: uuid.UUID
) -> list[ReactionGroupOut]:
    rows = await db.execute(
        select(Reaction.emoji, Reaction.user_id).where(Reaction.message_id == message_id)
    )
    by_emoji: dict[str, list[uuid.UUID]] = {}
    for emoji, uid in rows.all():
        by_emoji.setdefault(emoji, []).append(uid)
    return [
        ReactionGroupOut(emoji=e, count=len(uids), user_ids=uids)
        for e, uids in by_emoji.items()
    ]
```

> 若 `services/conversations.py` 從 `app.schemas` import 會造成循環匯入，改為在函式內 `from app.schemas import ReactionGroupOut`（本專案 schemas 不 import services，通常無循環；若 pytest 收集時報循環匯入再改用函式內 import）。

- [ ] **Step 5: 改 `routers/conversations.py` 的 `list_messages`** — 組裝 MessageOut 時帶新欄位並遮蔽已刪：

```python
from app.services.conversations import (
    get_attachment_for_message,
    get_conversation_for_member,
    get_reaction_groups,
    read_count,
)
# ... 在 list_messages 的推導迴圈內：
    out = []
    for m in messages:
        deleted = m.deleted_at is not None
        att = None if deleted else await get_attachment_for_message(db, m.id)
        groups = [] if deleted else await get_reaction_groups(db, m.id)
        out.append(
            MessageOut(
                id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
                content="" if deleted else m.content, created_at=m.created_at,
                read_count=await read_count(db, m.id),
                attachment=AttachmentOut.model_validate(att) if att else None,
                edited_at=m.edited_at,
                deleted=deleted,
                reactions=groups,
            )
        )
    return out
```

- [ ] **Step 6: 跑測試 + 全後端回歸**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS（新測試 + 既有全綠；MessageOut 新欄位有預設值不影響既有）

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/app/services/conversations.py backend/app/routers/conversations.py backend/tests/test_message_actions_rest.py
git commit -m "[msg-actions][feat][backend] MessageOut edited/deleted/reactions + 歷史聚合"
```

---

### Task 3: WebSocket edit / delete / react

**Files:**
- Modify: `backend/app/ws/router.py`
- Test: `backend/tests/test_ws_message_actions.py`

**Interfaces:**
- Consumes: Task 1/2（`Reaction`、`get_reaction_groups`、`get_conversation_for_member`、`get_other_member_ids`、`QUICK_REACTIONS`）。
- Produces（WS 行為）：
  - Client→Server：`{type:"edit", message_id, content}`、`{type:"delete", message_id}`、`{type:"react", message_id, emoji}`
  - Server→Client：`{type:"message_updated", message}` 廣播給該對話所有在線成員（含操作者）
  - `_serialize_message(db, msg, read_count=0)` 改為 async，帶 `edited_at`/`deleted`/`reactions`，並遮蔽已刪

- [ ] **Step 1: 改序列化為 async 並帶新欄位** — `backend/app/ws/router.py`：

```python
from datetime import datetime, timezone
from sqlalchemy import delete as sa_delete, select
from app.models import Attachment, Message, Reaction, User
from app.reactions import QUICK_REACTIONS
from app.schemas import AttachmentOut
from app.services.conversations import (
    get_conversation_for_member,
    get_other_member_ids,
    get_reaction_groups,
    mark_read,
    read_count as read_count_fn,
)


async def _serialize_message(db, msg: Message, read_count: int = 0) -> dict:
    deleted = msg.deleted_at is not None
    attachment = None
    if not deleted:
        att_res = await db.execute(select(Attachment).where(Attachment.message_id == msg.id))
        attachment = att_res.scalar_one_or_none()
    groups = [] if deleted else await get_reaction_groups(db, msg.id)
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": "" if deleted else msg.content,
        "created_at": msg.created_at.astimezone(timezone.utc).isoformat(),
        "read_count": read_count,
        "attachment": (
            AttachmentOut.model_validate(attachment).model_dump(mode="json")
            if attachment else None
        ),
        "edited_at": msg.edited_at.astimezone(timezone.utc).isoformat() if msg.edited_at else None,
        "deleted": deleted,
        "reactions": [g.model_dump(mode="json") for g in groups],
    }
```

> 同步更新 `_handle_send`：移除舊的同步 `_serialize_message(message, attachment=attachment)` 呼叫，改為 `payload = await _serialize_message(db, message)`（在 `async with db_module.SessionLocal() as db` 區塊內、commit 之後呼叫）。

- [ ] **Step 2: 在 `_handle_client_message` 分派新類型** — 既有 if/elif 後加：

```python
    elif msg_type == "edit":
        await _handle_edit(websocket, user, data)
    elif msg_type == "delete":
        await _handle_delete(websocket, user, data)
    elif msg_type == "react":
        await _handle_react(websocket, user, data)
```

- [ ] **Step 3: 加三個 handler + 廣播輔助** — `backend/app/ws/router.py`：

```python
async def _broadcast_updated(db, conv_id, actor_id, message: Message) -> None:
    payload = await _serialize_message(db, message, read_count=await read_count_fn(db, message.id))
    recipients = await get_other_member_ids(db, conv_id, actor_id)
    # 含操作者本人（多裝置同步）
    for rid in [actor_id, *recipients]:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message_updated", "message": payload})


def _parse_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _handle_edit(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    content = (data.get("content") or "").strip()
    if mid is None or not content:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id or msg.deleted_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        msg.content = content
        msg.edited_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def _handle_delete(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if msg.deleted_at is None:
            msg.deleted_at = datetime.now(timezone.utc)
            msg.content = ""
            await db.commit()
            await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)


async def _handle_react(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    emoji = data.get("emoji")
    if mid is None or emoji not in QUICK_REACTIONS:
        await websocket.send_json({"type": "error", "reason": "invalid_reaction"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None or msg.deleted_at is not None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        existing = await db.execute(
            select(Reaction).where(
                Reaction.message_id == mid,
                Reaction.user_id == user.id,
                Reaction.emoji == emoji,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            db.add(Reaction(message_id=mid, user_id=user.id, emoji=emoji))
        else:
            await db.execute(sa_delete(Reaction).where(Reaction.id == row.id))
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
```

> 既有 `read_count` import 名稱衝突：上面把它 import 為 `read_count_fn`。`_handle_read` 等若已用 `read_count`，改引用 `read_count_fn`，或保留既有 import 名稱並讓 `_broadcast_updated` 用既有名稱——擇一保持一致，不要兩個名字並存。

- [ ] **Step 4: 寫測試** — `backend/tests/test_ws_message_actions.py`

```python
import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("wa@example.com", "Alice")
    bob = await register_user("wb@example.com", "Bob")
    await client.post("/contacts", json={"email": "wb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="orig")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edit_broadcasts_updated(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb, tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "edited!"})
            evt_a = wa.receive_json()
            evt_b = wb.receive_json()
            for evt in (evt_a, evt_b):
                assert evt["type"] == "message_updated"
                assert evt["message"]["content"] == "edited!"
                assert evt["message"]["edited_at"] is not None


async def test_edit_non_sender_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "edit", "message_id": mid, "content": "hack"})
            assert wb.receive_json()["reason"] == "forbidden"


async def test_delete_soft_masks_content(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            evt = wa.receive_json()
            assert evt["message"]["deleted"] is True
            assert evt["message"]["content"] == ""


async def test_react_toggle(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "👍"})
            on = wb.receive_json()
            grp = on["message"]["reactions"][0]
            assert grp["emoji"] == "👍" and grp["count"] == 1 and bid in grp["user_ids"]
            wb.send_json({"type": "react", "message_id": mid, "emoji": "👍"})
            off = wb.receive_json()
            assert off["message"]["reactions"] == []


async def test_react_invalid_emoji(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "🦄"})
            assert wb.receive_json()["reason"] == "invalid_reaction"
```

- [ ] **Step 5: 跑測試 + 全後端回歸**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS（既有 WS 測試仍綠；`message` ack 多了 edited_at/deleted/reactions 欄位，既有斷言不檢查它故不受影響）

- [ ] **Step 6: Commit**

```bash
git add backend/app/ws/router.py backend/tests/test_ws_message_actions.py
git commit -m "[msg-actions][feat][ws] edit/delete/react 與 message_updated 廣播"
```

---

### Task 4: 前端契約 + messageStore + store

**Files:**
- Modify: `frontend/contracts/index.ts`
- Modify: `frontend/chat/src/messageStore.ts`
- Modify: `frontend/chat/src/store.ts`
- Modify: `frontend/chat/src/messageStore.test.ts`、`frontend/chat/src/store.test.ts`
- Test: 上述兩個測試檔（新增案例）

**Interfaces:**
- Produces:
  - 契約：`ReactionGroup { emoji, count, user_ids: string[] }`；`Message` += `edited_at: string|null`、`deleted: boolean`、`reactions: ReactionGroup[]`；`ClientWsMessage` += edit/delete/react；`ServerWsMessage` += `message_updated`；`export const QUICK_REACTIONS`。
  - `applyMessageUpdate(list: ChatMessage[], message: Message): ChatMessage[]`（依 id 取代、找不到不動）
  - `makeOptimistic` 回傳補 `edited_at:null, deleted:false, reactions:[]`
  - store action `updateMessage(message: Message)`

- [ ] **Step 1: 改契約** — `frontend/contracts/index.ts`

```typescript
export interface ReactionGroup {
  emoji: string;
  count: number;
  user_ids: string[];
}

export interface Message {            // 既有欄位不變，新增三個：
  edited_at: string | null;
  deleted: boolean;
  reactions: ReactionGroup[];
}

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];
```

`ClientWsMessage` 加三變體、`ServerWsMessage` 加一變體：

```typescript
  | { type: 'edit'; message_id: string; content: string }
  | { type: 'delete'; message_id: string }
  | { type: 'react'; message_id: string; emoji: string }
// ServerWsMessage：
  | { type: 'message_updated'; message: Message }
```

- [ ] **Step 2: 更新測試 helper + 新增案例** — `messageStore.test.ts` 與 `store.test.ts` 的 `realMessage`/`realMsg` 回傳物件補 `edited_at: null, deleted: false, reactions: []`。在 `messageStore.test.ts` 新增：

```typescript
import { applyMessageUpdate } from './messageStore';

it('applyMessageUpdate 依 id 取代該則', () => {
  const list = fromHistory([realMessage('m1', 'a'), realMessage('m2', 'b')]);
  const updated = { ...realMessage('m1', 'a'), content: 'edited', edited_at: '2026-06-20T00:00:00Z' };
  const next = applyMessageUpdate(list, updated);
  expect(next.find((m) => m.id === 'm1')!.content).toBe('edited');
  expect(next.find((m) => m.id === 'm1')!.edited_at).toBe('2026-06-20T00:00:00Z');
  expect(next.find((m) => m.id === 'm2')!.content).toBe('b');
});

it('applyMessageUpdate 找不到 id 時不動', () => {
  const list = fromHistory([realMessage('m1', 'a')]);
  const next = applyMessageUpdate(list, { ...realMessage('zzz', 'x') });
  expect(next).toHaveLength(1);
  expect(next[0].id).toBe('m1');
});
```

在 `store.test.ts` 新增：

```typescript
it('updateMessage 套用到正確對話', () => {
  const s = useChatStore.getState();
  s.loadHistory('c1', [realMsg('m1')]);
  s.updateMessage({ ...realMsg('m1'), content: 'edited', conversation_id: 'c1' });
  expect(useChatStore.getState().messages['c1'][0].content).toBe('edited');
});
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts src/store.test.ts`
Expected: FAIL（`applyMessageUpdate` / `updateMessage` 未定義）

- [ ] **Step 4: 改 `messageStore.ts`** — `makeOptimistic` 補欄位、新增 `applyMessageUpdate`：

```typescript
// makeOptimistic 回傳物件加： edited_at: null, deleted: false, reactions: [],

/** 收到 message_updated：依 id 取代該則（保留 sent 狀態）；找不到則不動。 */
export function applyMessageUpdate(
  list: ChatMessage[],
  message: Message,
): ChatMessage[] {
  if (!list.some((m) => m.id === message.id)) return list;
  return list.map((m) =>
    m.id === message.id ? { ...message, status: 'sent' as const } : m,
  );
}
```

- [ ] **Step 5: 改 `store.ts`** — `ChatState` 介面加 `updateMessage`，並在 create 內實作：

```typescript
import { applyMessageUpdate, /* 既有... */ } from './messageStore';

  updateMessage: (message) =>
    set((s) => {
      const convId = message.conversation_id;
      const list = s.messages[convId];
      if (!list) return s;
      return { messages: { ...s.messages, [convId]: applyMessageUpdate(list, message) } };
    }),
```

並在 `ChatState` 介面宣告：`updateMessage: (message: Message) => void;`（import `Message` 型別）。

- [ ] **Step 6: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts src/store.test.ts`
Expected: PASS

> 此 Task 後 `Thread.test.tsx`（其 `msg()` helper 建 Message 字面值）會型別錯——Task 5 修。本 Task **只跑** messageStore + store 兩個測試檔，不跑全 tsc/vitest。

- [ ] **Step 7: Commit**

```bash
git add frontend/contracts/index.ts frontend/chat/src/messageStore.ts frontend/chat/src/store.ts frontend/chat/src/messageStore.test.ts frontend/chat/src/store.test.ts
git commit -m "[msg-actions][feat][contracts] 契約 edited/deleted/reactions + applyMessageUpdate + store.updateMessage"
```

---

### Task 5: Thread 泡泡 — 編輯/刪除/表情 UI

**Files:**
- Modify: `frontend/chat/src/components/Thread.tsx`
- Modify: `frontend/chat/src/components/Thread.test.tsx`

**Interfaces:**
- Consumes: Task 4（`Message.edited_at/deleted/reactions`、`QUICK_REACTIONS`）。
- Produces: `Thread` props `onEdit: (id, content) => void`、`onDelete: (id) => void`、`onReact: (id, emoji) => void`；`MessageBubble` 渲染已編輯/刪除佔位/表情列/編輯刪除鈕。

- [ ] **Step 1: 更新/新增測試** — `frontend/chat/src/components/Thread.test.tsx`

`msg()` helper 補 `edited_at: null, deleted: false, reactions: []`；既有 `<Thread .../>` render 補 `onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()}`。新增：

```typescript
it('已編輯顯示標記、已刪除顯示佔位', () => {
  render(
    <Thread title="Bob" isGroup={false} memberNames={{}}
      attachmentUrl={(id) => id}
      messages={[
        msg({ id: 'm1', content: 'hi', edited_at: '2026-06-20T00:00:00Z' }),
        msg({ id: 'm2', deleted: true, content: '' }),
      ]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
      onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()} />,
  );
  expect(screen.getByText('已編輯')).toBeInTheDocument();
  expect(screen.getByText('此訊息已刪除')).toBeInTheDocument();
});

it('表情 chip 高亮並可 toggle', () => {
  const onReact = vi.fn();
  render(
    <Thread title="Bob" isGroup={false} memberNames={{}}
      attachmentUrl={(id) => id}
      messages={[msg({ id: 'm1', reactions: [{ emoji: '👍', count: 1, user_ids: ['me'] }] })]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
      onEdit={vi.fn()} onDelete={vi.fn()} onReact={onReact} />,
  );
  fireEvent.click(screen.getByRole('button', { name: /👍 1/ }));
  expect(onReact).toHaveBeenCalledWith('m1', '👍');
});

it('自己的訊息可刪除', () => {
  const onDelete = vi.fn();
  render(
    <Thread title="Bob" isGroup={false} memberNames={{}}
      attachmentUrl={(id) => id}
      messages={[msg({ id: 'm1', sender_id: 'me', content: 'mine' })]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
      onEdit={vi.fn()} onDelete={onDelete} onReact={vi.fn()} />,
  );
  fireEvent.click(screen.getByRole('button', { name: '刪除' }));
  expect(onDelete).toHaveBeenCalledWith('m1');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: FAIL（Thread 不接受 onEdit/onDelete/onReact；無「已編輯」「此訊息已刪除」「刪除」等）

- [ ] **Step 3: 改 `Thread.tsx`**

`ThreadProps` 加 `onEdit`/`onDelete`/`onReact`，傳給 `MessageBubble`。`MessageBubble` 簽名加這三者 + `currentUserId`。重點渲染（在現有泡泡結構內）：

```tsx
// 1) 已刪除：整個泡泡內容換成佔位
if (message.deleted) {
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div className="max-w-[70%] rounded-2xl bg-slate-100 px-4 py-2 text-sm italic text-slate-400">
        此訊息已刪除
      </div>
    </div>
  );
}

// 2) 內容區（沿用既有：sender 名、附件、content）。content <p> 後、狀態列：
//    狀態列加「已編輯」：
{message.edited_at && <span className="text-xs opacity-70">已編輯</span>}

// 3) 表情列（泡泡下方，所有未刪訊息）：
<div className="mt-1 flex flex-wrap items-center gap-1">
  {message.reactions.map((r) => (
    <button
      key={r.emoji}
      onClick={() => onReact(message.id, r.emoji)}
      className={`rounded-full px-2 py-0.5 text-xs ${
        r.user_ids.includes(currentUserId) ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'
      }`}
    >
      {r.emoji} {r.count}
    </button>
  ))}
  <ReactionPicker onPick={(e) => onReact(message.id, e)} />
</div>

// 4) 自己且未刪：編輯/刪除鈕；編輯為行內輸入
{mine && (
  editing ? (
    <form onSubmit={(e) => { e.preventDefault(); const v = draft.trim(); if (v) onEdit(message.id, v); setEditing(false); }}>
      <input className="input text-slate-800" value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="編輯訊息" />
      <button type="submit">儲存</button>
      <button type="button" onClick={() => setEditing(false)}>取消</button>
    </form>
  ) : (
    <div className="mt-0.5 flex gap-2 text-xs opacity-70">
      <button onClick={() => { setDraft(message.content); setEditing(true); }}>編輯</button>
      <button onClick={() => onDelete(message.id)}>刪除</button>
    </div>
  )
)}
```

`MessageBubble` 內以 `useState` 管 `editing`/`draft`。`ReactionPicker` 為同檔小元件：一個「＋」鈕，點擊 toggle 顯示 `QUICK_REACTIONS`（`import { QUICK_REACTIONS } from '../../../contracts'`）一排 emoji，點選呼叫 `onPick`。`MessageBubble` 需從 `Thread` 取得 `currentUserId`（沿用既有傳入）。

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: PASS

> 此 Task 後 `ChatApp.tsx` 未傳 onEdit/onDelete/onReact，全 `tsc` 會錯（預期）；Task 6 補齊。本 Task 只跑 Thread 測試。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/components/Thread.tsx frontend/chat/src/components/Thread.test.tsx
git commit -m "[msg-actions][feat][chat] 泡泡編輯/刪除/表情 UI"
```

---

### Task 6: ChatApp 整合

**Files:**
- Modify: `frontend/chat/src/ChatApp.tsx`
- Test: 以 `tsc --noEmit` + 全 vitest 綠燈為準

**Interfaces:**
- Consumes: Task 4（`store.updateMessage`）、Task 5（Thread `onEdit/onDelete/onReact`）。

- [ ] **Step 1: 改 `handleServerMessage`** — 加 `message_updated`：

```typescript
case 'message_updated':
  st.updateMessage(msg.message);
  break;
```
（`st` 即 `useChatStore.getState()`；`msg.message` 為更新後訊息。）

- [ ] **Step 2: 加三個動作 callback** — `ChatApp.tsx`：

```typescript
const editMessage = useCallback((id: string, content: string) => {
  socketRef.current?.send({ type: 'edit', message_id: id, content });
}, []);
const deleteMessage = useCallback((id: string) => {
  socketRef.current?.send({ type: 'delete', message_id: id });
}, []);
const toggleReaction = useCallback((id: string, emoji: string) => {
  socketRef.current?.send({ type: 'react', message_id: id, emoji });
}, []);
```

- [ ] **Step 3: 傳給 `<Thread>`** — 補 `onEdit={editMessage} onDelete={deleteMessage} onReact={toggleReaction}`。

- [ ] **Step 4: typecheck + 全 vitest（chat）+ shell typecheck**

Run:
```bash
cd frontend/chat && npx tsc --noEmit && npx vitest run
cd ../shell && npx tsc --noEmit
```
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/ChatApp.tsx
git commit -m "[msg-actions][feat][chat] ChatApp 串接 edit/delete/react 與 message_updated"
```

---

### Task 7: 端到端煙霧 + 文件

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md`、`progress.md`、`README.md`

- [ ] **Step 1: 啟動整套**（依 CLAUDE.md：backend SQLite、auth/chat build+preview、shell dev；`backend/dev.db` 跑 `alembic upgrade head` 到 0004）。

- [ ] **Step 2: 瀏覽器煙霧** — 登入 → 開對話 → 對自己的訊息：編輯（顯示「已編輯」、內容更新）、刪除（顯示「此訊息已刪除」佔位）；對任一訊息按表情（chip 出現計數、再按移除）。多開一個無痕視窗以另一使用者確認即時同步。截圖存 `docs/`。

- [ ] **Step 3: 更新文件** — MVP spec 把「訊息編輯/刪除/表情回應」標為已實作（連到本設計）；`progress.md` 補現況與 follow-up；`README.md` 補說明。

- [ ] **Step 4: 全測試總跑**

Run:
```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
cd ../frontend/chat && npx vitest run && npx tsc --noEmit
cd ../shell && npx vitest run && npx tsc --noEmit
cd ../auth && npx vitest run && npx tsc --noEmit
```
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add docs progress.md README.md
git commit -m "[msg-actions][docs][repo] 編輯/刪除/表情完成，更新設計/進度/README"
```

---

## Self-Review（計畫對照 spec）

- **Spec §3 資料模型（edited_at/deleted_at、Reaction、白名單）** → Task 1。✅
- **Spec §3 MessageOut（edited_at/deleted/reactions、user_ids 形狀、遮蔽已刪）** → Task 2。✅
- **Spec §4 WS（edit/delete/react、message_updated 廣播含本人、序列化）** → Task 3。✅
- **Spec §5 前端（契約、applyMessageUpdate、store.updateMessage、Thread UI、ChatApp）** → Task 4/5/6。✅
- **Spec §6 測試** → 各 Task TDD；Task 7 端到端。✅
- **Spec §7 安全（限本人/成員、emoji 白名單、遮蔽已刪）** → Task 1（白名單）、Task 2（遮蔽）、Task 3（權限）。✅

型別一致性：`ReactionGroupOut`(後端 emoji/count/user_ids) ↔ `ReactionGroup`(前端) 一致；`MessageOut.edited_at/deleted/reactions` ↔ `Message` 前端三欄位一致；WS `_serialize_message` 輸出與 `MessageOut` 同形（edited_at ISO、deleted bool、reactions 陣列）；client `edit/delete/react` ↔ 後端 `_handle_edit/_handle_delete/_handle_react` 讀取的欄位一致；`message_updated` ↔ 前端 `case 'message_updated'`；`applyMessageUpdate`/`updateMessage`/`onEdit`/`onDelete`/`onReact` 跨 Task 命名一致。

> 耦合備註：Task 4 改 `Message`（加必填 edited_at/deleted/reactions）會讓 `Thread.test.tsx` 與 `ChatApp` 型別暫時失敗，分別於 Task 5、Task 6 修復；故 Task 4 只跑 messageStore+store 測試、Task 5 只跑 Thread 測試、Task 6 才跑全 tsc（與前兩個功能前端流程相同模式）。
> WS `_serialize_message` 由同步改為 async，Task 3 Step 1 已同步更新 `_handle_send` 的呼叫點；務必確認沒有其他同步呼叫點殘留。
