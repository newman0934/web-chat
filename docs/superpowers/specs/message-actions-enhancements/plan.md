# 訊息動作小增強 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在現有 edit/delete/react 訊息動作上，補上「編輯歷史 + 15 分鐘編輯時限」「自由 emoji 選擇器」「寄件人 5 分鐘內還原已刪除訊息」。

**Architecture:** 沿用既有 WebSocket 協定與單一 `message_updated` 廣播；新增 client→server 類型 `restore`；編輯歷史另以 on-demand REST 端點 `GET /messages/{id}/edits` 提供。資料面新增 `MessageEdit` 版本表，刪除改為「保留 content + 輸出遮蔽」以支援還原。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic（後端）；React 18 + zustand + Vitest（chat remote）；emoji 選擇器用 `@emoji-mart/react` + `@emoji-mart/data`。

## Global Constraints

- 編輯時窗 `EDIT_WINDOW = 15 分鐘`（以 `message.created_at` 起算）；超過 → WS 回 `{"type":"error","reason":"edit_window_passed"}`。
- 還原時窗 `RESTORE_WINDOW = 5 分鐘`（以 `message.deleted_at` 起算）；超過 → `{"type":"error","reason":"restore_window_passed"}`。
- 還原與編輯嚴格限 `sender_id == user`；非寄件人 / 非法狀態 → `{"type":"error","reason":"forbidden"}`；缺 `message_id` → `{"type":"error","reason":"invalid_payload"}`。
- 刪除**不再清空 DB content**（只設 `deleted_at`）；所有輸出端點（WS、REST 分頁、歷史端點）對 `deleted` 訊息一律遮蔽：`content=""`、`attachment=null`、`reactions=[]`。
- emoji 放寬為「單一 emoji」驗證：`strip()` 後非空、`len ≤ 8` Unicode 字元、不含任何 ASCII 英數或空白字元；不符 → `{"type":"error","reason":"invalid_reaction"}`。不再用固定白名單。
- 編輯歷史端點 `GET /messages/{message_id}/edits`：權限 = 對話成員（`get_conversation_for_member`），非成員 / 訊息不存在 → 404；已刪除訊息 → 403。回傳「各舊版本 + 目前版本」由舊到新，每筆 `{content, created_at}`。
- `MessageEdit` 快照語意：編輯時把「目前 content + 它的生效時間（`edited_at or created_at`）」寫入一列，再覆寫成新內容、`edited_at = now()`。
- 前端 contracts 的 `Message.deleted_at` 用 **optional**（`deleted_at?: string | null`），與既有 `kind?` 同風格，避免破壞既有 Message fixtures 的 typecheck。
- 時窗常數前後端各一份（後端 `app/message_policy.py`、前端 `frontend/contracts/index.ts`）；前端常數只控制按鈕顯隱，安全邊界一律在後端。
- Commit 標題格式：`[msg-actions][type][scope] description`，內文結尾保留 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 後端測試一律用 `backend/.venv/Scripts/python.exe -m pytest`（PATH 上的 python 是 Store stub，不可用）。

---

### Task 1: `MessageEdit` 版本表（model + migration 0007）

**Files:**
- Create: `backend/app/models/message_edit.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0007_message_edits.py`
- Test: `backend/tests/test_message_edit_model.py`

**Interfaces:**
- Produces: `MessageEdit` ORM（欄位 `id: uuid`、`message_id: uuid`、`content: str`、`created_at: datetime`），匯出於 `app.models`。後續 Task 2/3 依賴它。

- [ ] **Step 1: Write the failing test**

`backend/tests/test_message_edit_model.py`：
```python
import uuid

import pytest

from app.models import Conversation, ConversationMember, Message, MessageEdit, User

pytestmark = pytest.mark.asyncio


async def test_message_edit_round_trips(session_factory):
    async with session_factory() as s:
        u = User(email="me@x.com", display_name="Me", password_hash="h")
        s.add(u)
        await s.flush()
        conv = Conversation(type="direct", direct_key=f"{u.id}:{u.id}")
        s.add(conv)
        await s.flush()
        s.add(ConversationMember(conversation_id=conv.id, user_id=u.id))
        msg = Message(conversation_id=conv.id, sender_id=u.id, content="v2")
        s.add(msg)
        await s.flush()
        from datetime import datetime, timezone
        edit = MessageEdit(
            message_id=msg.id, content="v1", created_at=datetime.now(timezone.utc)
        )
        s.add(edit)
        await s.commit()
        got = await s.get(MessageEdit, edit.id)
        assert got is not None
        assert got.content == "v1"
        assert got.message_id == msg.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_message_edit_model.py -v`（在 `backend/` 下）
Expected: FAIL with `ImportError: cannot import name 'MessageEdit'`.

- [ ] **Step 3: Create the model**

`backend/app/models/message_edit.py`：
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MessageEdit(Base):
    """訊息的某個歷史版本（被後續編輯取代前的內容）。

    每次編輯前，把「目前 content + 它的生效時間」快照成一列；
    歷史 = 這些列（由舊到新）＋ 目前的 Message.content。
    """

    __tablename__ = "message_edits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # created_at 顯式帶入（= 該版本生效時間），故不設 server_default。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
```

- [ ] **Step 4: Register in models package**

`backend/app/models/__init__.py` 加入 import 與 `__all__`：
```python
from app.models.attachment import Attachment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.message import Message
from app.models.message_edit import MessageEdit
from app.models.message_read import MessageRead
from app.models.reaction import Reaction
from app.models.user import User

__all__ = [
    "User", "Contact", "Conversation", "ConversationMember",
    "Message", "MessageEdit", "MessageRead", "Attachment", "Reaction",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_message_edit_model.py -v`
Expected: PASS（conftest 用 `Base.metadata.create_all`，新表會自動建立）。

- [ ] **Step 6: Write the Alembic migration**

`backend/alembic/versions/0007_message_edits.py`：
```python
"""message_edits 版本紀錄表

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_edits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_message_edits_message_id"), "message_edits", ["message_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_message_edits_message_id"), table_name="message_edits")
    op.drop_table("message_edits")
```

- [ ] **Step 7: Add a migration smoke test**

在 `backend/tests/test_message_edit_model.py` 末尾追加（沿用 0005/0006 遷移測試的 shell-out 模式）：
```python
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0007_creates_table(tmp_path):
    db = tmp_path / "mig.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "message_edits" in names
```

- [ ] **Step 8: Run both tests**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_message_edit_model.py -v`
Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/message_edit.py backend/app/models/__init__.py backend/alembic/versions/0007_message_edits.py backend/tests/test_message_edit_model.py
git commit -m "[msg-actions][feat][backend] MessageEdit 版本表 + 0007 遷移"
```

---

### Task 2: 編輯快照歷史 + 15 分鐘編輯時限（WS `edit`）

**Files:**
- Create: `backend/app/message_policy.py`
- Modify: `backend/app/ws/router.py`（`_handle_edit`，約 286-301 行；新增 `_as_utc` helper）
- Test: `backend/tests/test_ws_edit_history.py`

**Interfaces:**
- Consumes: `MessageEdit`（Task 1）。
- Produces: `app.message_policy.EDIT_WINDOW: timedelta`；`_handle_edit` 行為：在窗內編輯時寫一筆 `MessageEdit` 快照並更新訊息，超窗回 `edit_window_passed`。

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_ws_edit_history.py`：
```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.main import app
from app.models import Message, MessageEdit

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory, content="orig"):
    alice = await register_user("eha@example.com", "Alice")
    bob = await register_user("ehb@example.com", "Bob")
    await client.post("/contacts", json={"email": "ehb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content=content)
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edit_snapshots_previous_version(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            evt = wa.receive_json()
            assert evt["message"]["content"] == "v2"
    async with session_factory() as s:
        rows = (await s.execute(
            select(MessageEdit).where(MessageEdit.message_id == uuid.UUID(mid))
        )).scalars().all()
        assert [e.content for e in rows] == ["v1"]


async def test_two_edits_build_version_chain(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            wa.receive_json()
            wa.send_json({"type": "edit", "message_id": mid, "content": "v3"})
            wa.receive_json()
    async with session_factory() as s:
        rows = (await s.execute(
            select(MessageEdit).where(MessageEdit.message_id == uuid.UUID(mid))
            .order_by(MessageEdit.created_at)
        )).scalars().all()
        assert [e.content for e in rows] == ["v1", "v2"]


async def test_edit_past_window_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    # 把 created_at 推到 16 分鐘前 → 超過 15 分鐘編輯窗
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        await s.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "late"})
            evt = wa.receive_json()
            assert evt["type"] == "error"
            assert evt["reason"] == "edit_window_passed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_edit_history.py -v`
Expected: FAIL（`test_edit_snapshots_previous_version` 找不到 MessageEdit 列；`test_edit_past_window_rejected` 收到 `message_updated` 而非 error）。

- [ ] **Step 3: Create the policy module**

`backend/app/message_policy.py`：
```python
"""訊息動作的時窗與驗證常數（WS 端點共用；前端 contracts 另有同份時窗）。"""

from datetime import timedelta

EDIT_WINDOW = timedelta(minutes=15)
```

- [ ] **Step 4: Update `_handle_edit` in `backend/app/ws/router.py`**

在檔案 import 區補上：
```python
from app.message_policy import EDIT_WINDOW
from app.models import Attachment, Message, MessageEdit, Reaction, User
```
（把既有 `from app.models import Attachment, Message, Reaction, User` 改成含 `MessageEdit`。）

在 `_parse_uuid` 附近新增 helper：
```python
def _as_utc(dt: datetime) -> datetime:
    """把可能為 naive 的 datetime 視為 UTC，供時窗比較。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
```

把 `_handle_edit` 整段換成：
```python
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
        now = datetime.now(timezone.utc)
        if now - _as_utc(msg.created_at) > EDIT_WINDOW:
            await websocket.send_json({"type": "error", "reason": "edit_window_passed"})
            return
        # 快照目前版本（content + 它的生效時間）後再覆寫。
        prev_at = msg.edited_at or msg.created_at
        db.add(MessageEdit(message_id=msg.id, content=msg.content, created_at=prev_at))
        msg.content = content
        msg.edited_at = now
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_edit_history.py tests/test_ws_message_actions.py -v`
Expected: 全 PASS（既有 edit 廣播測試仍綠）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/message_policy.py backend/app/ws/router.py backend/tests/test_ws_edit_history.py
git commit -m "[msg-actions][feat][ws] 編輯快照版本歷史 + 15 分鐘編輯時限"
```

---

### Task 3: 編輯歷史 REST 端點 `GET /messages/{id}/edits`

**Files:**
- Create: `backend/app/routers/messages.py`
- Modify: `backend/app/main.py:7,29`（import 並掛載 messages router）
- Modify: `backend/app/schemas.py`（新增 `MessageVersionOut`）
- Test: `backend/tests/test_message_edits_rest.py`

**Interfaces:**
- Consumes: `MessageEdit`（Task 1）、`_handle_edit` 寫入的版本鏈（Task 2）。
- Produces: `GET /messages/{message_id}/edits` → `list[MessageVersionOut]`（`{content: str, created_at: datetime}`，由舊到新，最後一筆為目前版本）。前端 Task 6 依賴此形狀。

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_message_edits_rest.py`：
```python
import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory, content="v1"):
    alice = await register_user("mra@example.com", "Alice")
    bob = await register_user("mrb@example.com", "Bob")
    await client.post("/contacts", json={"email": "mrb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content=content)
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_edits_returns_versions_in_order(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="v1")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "edit", "message_id": mid, "content": "v2"})
            wa.receive_json()
            wa.send_json({"type": "edit", "message_id": mid, "content": "v3"})
            wa.receive_json()
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 200, resp.text
    contents = [v["content"] for v in resp.json()]
    assert contents == ["v1", "v2", "v3"]  # 舊版 v1、v2 + 目前 v3


async def test_edits_unedited_returns_current_only(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory, content="only")
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 200
    assert [v["content"] for v in resp.json()] == ["only"]


async def test_edits_non_member_404(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    carol = await register_user("mrc@example.com", "Carol")
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(carol))
    assert resp.status_code == 404


async def test_edits_deleted_message_403(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(
        client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            wa.receive_json()
    resp = await client.get(f"/messages/{mid}/edits", headers=auth_headers(alice))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_message_edits_rest.py -v`
Expected: FAIL with 404（路由不存在）。

- [ ] **Step 3: Add the schema**

`backend/app/schemas.py`，在 `MessageOut` 之後新增：
```python
class MessageVersionOut(BaseModel):
    content: str
    created_at: datetime
```

- [ ] **Step 4: Create the router**

`backend/app/routers/messages.py`：
```python
"""單則訊息層級的 REST 端點（目前：編輯歷史）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Message, MessageEdit, User
from app.schemas import MessageVersionOut
from app.services.conversations import get_conversation_for_member

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("/{message_id}/edits", response_model=list[MessageVersionOut])
async def list_message_edits(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="查無此訊息")
    conv = await get_conversation_for_member(db, msg.conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此訊息或無權限")
    if msg.deleted_at is not None:
        raise HTTPException(status_code=403, detail="訊息已刪除，無法檢視編輯歷史")

    rows = await db.execute(
        select(MessageEdit)
        .where(MessageEdit.message_id == message_id)
        .order_by(MessageEdit.created_at)
    )
    versions = [
        MessageVersionOut(content=e.content, created_at=e.created_at)
        for e in rows.scalars().all()
    ]
    # 目前版本當最後一筆（生效時間 = edited_at 或原始 created_at）。
    versions.append(
        MessageVersionOut(content=msg.content, created_at=msg.edited_at or msg.created_at)
    )
    return versions
```

- [ ] **Step 5: Mount the router**

`backend/app/main.py`：
```python
from app.routers import auth, contacts, conversations, messages, uploads, users
```
並在 `app.include_router(conversations.router)` 之後加：
```python
app.include_router(messages.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_message_edits_rest.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/messages.py backend/app/main.py backend/app/schemas.py backend/tests/test_message_edits_rest.py
git commit -m "[msg-actions][feat][backend] GET /messages/{id}/edits 編輯歷史端點"
```

---

### Task 4: 刪除保留 content + `deleted_at` 輸出 + 還原 WS handler

**Files:**
- Modify: `backend/app/schemas.py`（`MessageOut` 加 `deleted_at`）
- Modify: `backend/app/message_policy.py`（加 `RESTORE_WINDOW`）
- Modify: `backend/app/ws/router.py`（`_serialize_message` 加 `deleted_at`；`_handle_delete` 不再清空 content；新增 `_handle_restore` + 路由）
- Modify: `backend/app/routers/conversations.py`（`list_messages` 的 `MessageOut` 加 `deleted_at`；`_system_message_payload` 加 `deleted_at: None`）
- Test: `backend/tests/test_ws_restore.py`

**Interfaces:**
- Consumes: `_as_utc`（Task 2）。
- Produces: `app.message_policy.RESTORE_WINDOW: timedelta`；client→server `{type:"restore", message_id}`；`MessageOut.deleted_at`（已刪訊息有值，否則 None）。

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_ws_restore.py`：
```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models import Message

pytestmark = pytest.mark.asyncio


async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("rsa@example.com", "Alice")
    bob = await register_user("rsb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rsb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="secret")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_delete_keeps_db_content_masks_output(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            evt = wa.receive_json()
            assert evt["message"]["content"] == ""           # 輸出遮蔽
            assert evt["message"]["deleted"] is True
            assert evt["message"]["deleted_at"] is not None
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        assert m.content == "secret"                          # DB 仍保留原文


async def test_restore_within_window(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            wa.receive_json(); wb.receive_json()
            wa.send_json({"type": "restore", "message_id": mid})
            ea = wa.receive_json(); eb = wb.receive_json()
            for evt in (ea, eb):
                assert evt["type"] == "message_updated"
                assert evt["message"]["deleted"] is False
                assert evt["message"]["content"] == "secret"
                assert evt["message"]["deleted_at"] is None


async def test_restore_non_sender_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa, \
             tc.websocket_connect(f"/ws?token={bob}") as wb:
            wa.send_json({"type": "delete", "message_id": mid})
            wa.receive_json(); wb.receive_json()
            wb.send_json({"type": "restore", "message_id": mid})
            evt = wb.receive_json()
            assert evt["type"] == "error" and evt["reason"] == "forbidden"


async def test_restore_past_window_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "delete", "message_id": mid})
            wa.receive_json()
    # 把 deleted_at 推到 6 分鐘前 → 超過 5 分鐘還原窗
    async with session_factory() as s:
        m = await s.get(Message, uuid.UUID(mid))
        m.deleted_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        await s.commit()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "restore", "message_id": mid})
            evt = wa.receive_json()
            assert evt["type"] == "error" and evt["reason"] == "restore_window_passed"


async def test_restore_non_deleted_forbidden(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "restore", "message_id": mid})
            evt = wa.receive_json()
            assert evt["type"] == "error" and evt["reason"] == "forbidden"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_restore.py -v`
Expected: FAIL（`deleted_at` 不存在於 payload；`restore` 走到 `unknown_type`）。

- [ ] **Step 3: Add `RESTORE_WINDOW`**

`backend/app/message_policy.py` 加一行：
```python
RESTORE_WINDOW = timedelta(minutes=5)
```

- [ ] **Step 4: Add `deleted_at` to `MessageOut`**

`backend/app/schemas.py` 的 `MessageOut` 加欄位（放在 `deleted` 旁）：
```python
    deleted: bool = False
    deleted_at: datetime | None = None
```

- [ ] **Step 5: Serialize `deleted_at` + stop wiping content + restore handler**

`backend/app/ws/router.py`：

(a) `_serialize_message` 的回傳 dict 加一鍵（在 `"deleted": deleted,` 之後）：
```python
        "deleted": deleted,
        "deleted_at": msg.deleted_at.astimezone(timezone.utc).isoformat() if msg.deleted_at else None,
```

(b) import 補 `RESTORE_WINDOW`：
```python
from app.message_policy import EDIT_WINDOW, RESTORE_WINDOW
```

(c) `_handle_delete` 移除清空 content 那行：
```python
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
            await db.commit()
            await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
```

(d) 新增 `_handle_restore`（放在 `_handle_delete` 之後）：
```python
async def _handle_restore(websocket, user, data):
    mid = _parse_uuid(data.get("message_id"))
    if mid is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        msg = await db.get(Message, mid)
        if msg is None or msg.sender_id != user.id or msg.deleted_at is None:
            await websocket.send_json({"type": "error", "reason": "forbidden"})
            return
        if datetime.now(timezone.utc) - _as_utc(msg.deleted_at) > RESTORE_WINDOW:
            await websocket.send_json({"type": "error", "reason": "restore_window_passed"})
            return
        msg.deleted_at = None
        await db.commit()
        await db.refresh(msg)
        await _broadcast_updated(db, msg.conversation_id, user.id, msg)
```

(e) `_handle_client_message` 加分派（在 `elif msg_type == "delete":` 之後）：
```python
    elif msg_type == "restore":
        await _handle_restore(websocket, user, data)
```

- [ ] **Step 6: Add `deleted_at` to REST 序列化**

`backend/app/routers/conversations.py`：

(a) `list_messages` 的 `MessageOut(...)` 加一欄（在 `deleted=deleted,` 之後）：
```python
                deleted=deleted,
                deleted_at=m.deleted_at,
```

(b) `_system_message_payload` 回傳 dict 加一鍵（在 `"deleted": False,` 之後）：
```python
        "deleted": False,
        "deleted_at": None,
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_restore.py tests/test_ws_message_actions.py tests/test_message_actions_rest.py -v`
Expected: 全 PASS（既有刪除/廣播測試仍綠：`test_delete_soft_masks_content` 仍看到 `content==""`）。

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas.py backend/app/message_policy.py backend/app/ws/router.py backend/app/routers/conversations.py backend/tests/test_ws_restore.py
git commit -m "[msg-actions][feat][ws] 刪除保留原文 + deleted_at 輸出 + restore 還原"
```

---

### Task 5: 放寬表情驗證為「單一 emoji」

**Files:**
- Modify: `backend/app/message_policy.py`（加 `is_valid_reaction_emoji`）
- Modify: `backend/app/ws/router.py`（`_handle_react` 改用驗證函式，移除 `QUICK_REACTIONS` import 使用）
- Modify: `backend/tests/test_ws_message_actions.py`（既有 `test_react_invalid_emoji` 改用 ASCII 文字當無效輸入）
- Test: `backend/tests/test_reaction_validation.py`

**Interfaces:**
- Produces: `app.message_policy.is_valid_reaction_emoji(value) -> bool`。

> ⚠️ 既有 `test_react_invalid_emoji` 用 `🦄` 期望 `invalid_reaction`。放寬後 `🦄` 變成合法單一 emoji，該測試**必須改**成用 ASCII 文字（如 `"hello"`）才仍是無效輸入——否則它會錯誤地紅。本 Task 一併修正。

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_reaction_validation.py`：
```python
import uuid

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.message_policy import is_valid_reaction_emoji
from app.models import Message

pytestmark = pytest.mark.asyncio


def test_is_valid_reaction_emoji_unit():
    assert is_valid_reaction_emoji("🎉") is True
    assert is_valid_reaction_emoji("👍") is True
    assert is_valid_reaction_emoji("hello") is False     # ASCII 文字
    assert is_valid_reaction_emoji("a") is False
    assert is_valid_reaction_emoji("") is False
    assert is_valid_reaction_emoji("   ") is False
    assert is_valid_reaction_emoji("🎉🎉🎉🎉🎉") is False  # 超過 8 字元
    assert is_valid_reaction_emoji(None) is False


async def _pair_with_message(client, register_user, auth_headers, session_factory):
    alice = await register_user("rva@example.com", "Alice")
    bob = await register_user("rvb@example.com", "Bob")
    await client.post("/contacts", json={"email": "rvb@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    async with session_factory() as s:
        m = Message(conversation_id=uuid.UUID(conv["id"]), sender_id=uuid.UUID(aid), content="hi")
        s.add(m)
        await s.commit()
        mid = str(m.id)
    return alice, bob, conv["id"], mid


async def test_react_arbitrary_emoji_accepted(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "🎉"})
            evt = wb.receive_json()
            assert evt["type"] == "message_updated"
            assert evt["message"]["reactions"][0]["emoji"] == "🎉"


async def test_react_text_rejected(client, register_user, auth_headers, session_factory):
    alice, bob, conv_id, mid = await _pair_with_message(client, register_user, auth_headers, session_factory)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as wb:
            wb.send_json({"type": "react", "message_id": mid, "emoji": "lol"})
            assert wb.receive_json()["reason"] == "invalid_reaction"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_reaction_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'is_valid_reaction_emoji'`.

- [ ] **Step 3: Add the validator**

`backend/app/message_policy.py` 加：
```python
import re

_DISALLOWED_IN_EMOJI = re.compile(r"[A-Za-z0-9\s]")


def is_valid_reaction_emoji(value) -> bool:
    """是否為單一 emoji：strip 後非空、≤ 8 Unicode 字元、不含 ASCII 英數/空白。

    用形狀驗證取代固定白名單：擋住任意文字塞入，但允許白名單外的真 emoji。
    """
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s or len(s) > 8:
        return False
    return _DISALLOWED_IN_EMOJI.search(s) is None
```
（把 `import re` 放到檔案頂端的 import 區。）

- [ ] **Step 4: Update `_handle_react`**

`backend/app/ws/router.py`：把 `from app.reactions import QUICK_REACTIONS` 改為 `from app.message_policy import EDIT_WINDOW, RESTORE_WINDOW, is_valid_reaction_emoji`（合併既有 message_policy import，並移除 reactions import）。

`_handle_react` 的驗證行：
```python
    if mid is None or not is_valid_reaction_emoji(emoji):
        await websocket.send_json({"type": "error", "reason": "invalid_reaction"})
        return
```

- [ ] **Step 5: Fix the now-stale existing test**

`backend/tests/test_ws_message_actions.py::test_react_invalid_emoji`：把 `"emoji": "🦄"` 改成 ASCII 文字，使其仍是無效輸入：
```python
            wb.send_json({"type": "react", "message_id": mid, "emoji": "lol"})
            assert wb.receive_json()["reason"] == "invalid_reaction"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_reaction_validation.py tests/test_ws_message_actions.py -v`
Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/message_policy.py backend/app/ws/router.py backend/tests/test_reaction_validation.py backend/tests/test_ws_message_actions.py
git commit -m "[msg-actions][feat][ws] 表情放寬為單一 emoji 驗證（取代固定白名單）"
```

---

### Task 6: 前端契約 + ApiClient + messageStore（plumbing）

**Files:**
- Modify: `frontend/contracts/index.ts`
- Modify: `frontend/chat/src/messageStore.ts`（`makeOptimistic` 加 `deleted_at: null`）
- Modify: `frontend/chat/src/api.ts`（`getMessageEdits`）
- Test: `frontend/chat/src/api.test.ts`（新增；若已存在則追加）

**Interfaces:**
- Consumes: 後端 `GET /messages/{id}/edits`（Task 3）、`restore` WS 類型（Task 4）。
- Produces: contracts `MessageVersion`、`EDIT_WINDOW_MS`、`RESTORE_WINDOW_MS`、`Message.deleted_at?`、ClientWs `restore`；`ApiClient.getMessageEdits`。ChatApp 接線與 Thread props 由 Task 7 一併補齊。

- [ ] **Step 1: Update contracts**

`frontend/contracts/index.ts`：

(a) `Message` interface 加 optional 欄位（在 `deleted: boolean;` 之後）：
```ts
  deleted: boolean;
  deleted_at?: string | null;
```

(b) `ReactionGroup` / `QUICK_REACTIONS` 之後新增：
```ts
export interface MessageVersion {
  content: string;
  created_at: string;
}

/** 編輯 / 還原時窗（毫秒）；與後端各一份，前端只用來決定按鈕顯隱。 */
export const EDIT_WINDOW_MS = 15 * 60 * 1000;
export const RESTORE_WINDOW_MS = 5 * 60 * 1000;
```

(c) `ClientWsMessage` union 加一個變體（在 `delete` 之後）：
```ts
  | { type: 'restore'; message_id: string }
```

- [ ] **Step 2: Write the failing test for `getMessageEdits`**

`frontend/chat/src/api.test.ts`（若檔案已存在則只追加此 describe）：
```ts
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from './api';

afterEach(() => vi.restoreAllMocks());

describe('ApiClient.getMessageEdits', () => {
  it('打 GET /messages/{id}/edits 並回傳版本陣列', async () => {
    const versions = [
      { content: 'v1', created_at: '2026-06-21T00:00:00Z' },
      { content: 'v2', created_at: '2026-06-21T00:05:00Z' },
    ];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(versions), { status: 200 }),
    );
    const api = new ApiClient('http://api', 'tok');
    const got = await api.getMessageEdits('m1');
    expect(got).toEqual(versions);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api/messages/m1/edits',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer tok' }) }),
    );
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run（在 `frontend/chat/`）: `npm run test -- api.test.ts`
Expected: FAIL（`api.getMessageEdits is not a function`）。

- [ ] **Step 4: Implement `getMessageEdits`**

`frontend/chat/src/api.ts`：import 加 `MessageVersion`：
```ts
import type { Attachment, Contact, Conversation, GroupCreateRequest, Message, MessageVersion } from '../../contracts';
```
在 `listMessages` 之後加方法：
```ts
  /** 取得某訊息的編輯歷史（由舊到新，最後一筆為目前版本）。 */
  getMessageEdits(messageId: string) {
    return this.req<MessageVersion[]>(`/messages/${messageId}/edits`);
  }
```

- [ ] **Step 5: `makeOptimistic` 補 `deleted_at`**

`frontend/chat/src/messageStore.ts`：`makeOptimistic` 回傳物件加（在 `deleted: false,` 之後）：
```ts
    deleted: false,
    deleted_at: null,
```

- [ ] **Step 6: Run frontend tests + typecheck**

Run（在 `frontend/chat/`）:
```
npm run test -- api.test.ts
npm run typecheck
```
Expected: api 測試 PASS、`typecheck` 乾淨（本 Task 只動 contracts / messageStore / api，不碰 ChatApp / Thread，故型別應全綠）。

- [ ] **Step 7: Commit**

```bash
git add frontend/contracts/index.ts frontend/chat/src/messageStore.ts frontend/chat/src/api.ts frontend/chat/src/api.test.ts
git commit -m "[msg-actions][feat][contracts] MessageVersion/時窗常數 + getMessageEdits + messageStore deleted_at"
```

---

### Task 7: Thread UI — 編輯時窗、編輯歷史、還原、emoji-mart 選擇器

**Files:**
- Modify: `frontend/chat/package.json`（加 `@emoji-mart/data`、`@emoji-mart/react` 依賴）
- Create: `frontend/chat/src/components/EditHistoryPopover.tsx`
- Modify: `frontend/chat/src/components/Thread.tsx`（props、編輯鈕時窗、已編輯可點、還原鈕、emoji-mart picker）
- Modify: `frontend/chat/src/ChatApp.tsx`（`restoreMessage` / `loadEditHistory` helper + 傳給 Thread）
- Test: `frontend/chat/src/components/Thread.test.tsx`（追加案例）、`frontend/chat/src/components/EditHistoryPopover.test.tsx`（新增）

**Interfaces:**
- Consumes: contracts `EDIT_WINDOW_MS` / `RESTORE_WINDOW_MS` / `MessageVersion`、`ApiClient.getMessageEdits`、ClientWs `restore`（Task 6）。

> ⚠️ Thread 既有測試中的 `msg()` builder 用 `created_at: '2026-06-19T00:00:00Z'`（早於現在超過 15 分鐘）。因此「編輯鈕只在時窗內顯示」後，這些舊訊息**不再顯示「編輯」鈕**——但**刪除鈕無時限、永遠顯示**。既有測試 `自己的訊息可刪除` 點的是「刪除」，仍會通過。實作時務必把「編輯」與「刪除」拆開：刪除恆顯示、編輯僅時窗內顯示。

- [ ] **Step 1: Install emoji-mart**

Run（在 `frontend/chat/`）:
```
npm install @emoji-mart/data@^1.2.1 @emoji-mart/react@^1.1.1 emoji-mart@^5.6.0
```
確認 `package.json` 的 `dependencies` 出現這三個套件。

- [ ] **Step 2: Write the failing tests (Thread)**

`frontend/chat/src/components/Thread.test.tsx`：在檔案頂端加 emoji-mart 的 mock（避免 jsdom 載入真 picker）：
```tsx
vi.mock('@emoji-mart/react', () => ({
  default: ({ onEmojiSelect }: { onEmojiSelect: (e: { native: string }) => void }) => (
    <button type="button" onClick={() => onEmojiSelect({ native: '🎉' })}>
      mock-picker-pick
    </button>
  ),
}));
vi.mock('@emoji-mart/data', () => ({ default: {} }));
```
追加測試案例（用 `Date.now` 基準產生「剛剛」的 created_at）：
```tsx
function nowIso(offsetMs = 0) {
  return new Date(Date.now() - offsetMs).toISOString();
}

describe('Thread 小增強', () => {
  const base = {
    isGroup: false as const, memberNames: {}, currentUserId: 'me',
    canLoadMore: false, title: 'Bob',
    onLoadMore: vi.fn(), onSend: vi.fn(), onRetry: vi.fn(),
    onEdit: vi.fn(), onDelete: vi.fn(), onReact: vi.fn(),
    attachmentUrl: (id: string) => id, onUpload: vi.fn(),
    onRestore: vi.fn(), loadEditHistory: vi.fn(),
  };

  it('編輯鈕只在 15 分鐘內顯示；超時隱藏但刪除仍在', () => {
    const { rerender } = render(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'fresh', created_at: nowIso(60_000) })]} />,
    );
    expect(screen.getByRole('button', { name: '編輯' })).toBeInTheDocument();

    rerender(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'old', created_at: nowIso(16 * 60_000) })]} />,
    );
    expect(screen.queryByRole('button', { name: '編輯' })).toBeNull();
    expect(screen.getByRole('button', { name: '刪除' })).toBeInTheDocument();
  });

  it('點「已編輯」呼叫 loadEditHistory 並列出版本', async () => {
    const loadEditHistory = vi.fn().mockResolvedValue([
      { content: 'v1', created_at: '2026-06-21T00:00:00Z' },
      { content: 'v2', created_at: '2026-06-21T00:05:00Z' },
    ]);
    render(
      <Thread {...base} loadEditHistory={loadEditHistory}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'v2', edited_at: '2026-06-21T00:05:00Z', created_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByText('已編輯'));
    expect(loadEditHistory).toHaveBeenCalledWith('m1');
    expect(await screen.findByText('v1')).toBeInTheDocument();
  });

  it('已刪除 + 寄件人 + 5 分鐘內顯示還原鈕並呼叫 onRestore', () => {
    const onRestore = vi.fn();
    render(
      <Thread {...base} onRestore={onRestore}
        messages={[msg({ id: 'm1', sender_id: 'me', deleted: true, content: '', deleted_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '還原' }));
    expect(onRestore).toHaveBeenCalledWith('m1');
  });

  it('已刪除超過 5 分鐘不顯示還原鈕', () => {
    render(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', deleted: true, content: '', deleted_at: nowIso(6 * 60_000) })]} />,
    );
    expect(screen.queryByRole('button', { name: '還原' })).toBeNull();
  });

  it('emoji-mart 選擇器選 emoji 呼叫 onReact', () => {
    const onReact = vi.fn();
    render(
      <Thread {...base} onReact={onReact}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'hi', created_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '更多表情' }));
    fireEvent.click(screen.getByText('mock-picker-pick'));
    expect(onReact).toHaveBeenCalledWith('m1', '🎉');
  });
});
```

> 既有 `msg()` builder 已含全部必填欄位；`deleted_at` 為 optional，不必改 builder。新增測試透過 `over` 傳 `deleted_at` / `created_at`。

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm run test -- Thread.test.tsx`
Expected: FAIL（Thread 尚不接受 `onRestore` / `loadEditHistory`；無「還原」「更多表情」鈕；「已編輯」非按鈕）。

- [ ] **Step 4: Create `EditHistoryPopover`**

`frontend/chat/src/components/EditHistoryPopover.tsx`：
```tsx
import { useEffect, useState } from 'react';

import type { MessageVersion } from '../../../contracts';

/** 點「已編輯」後彈出的編輯歷史：載入版本陣列並逐版列出（最後一筆為目前）。 */
export function EditHistoryPopover({
  messageId,
  load,
  onClose,
}: {
  messageId: string;
  load: (id: string) => Promise<MessageVersion[]>;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<MessageVersion[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    load(messageId)
      .then((v) => { if (alive) setVersions(v); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [messageId, load]);

  return (
    <div className="absolute z-20 mt-1 w-64 rounded-xl border border-slate-200 bg-white p-3 text-left text-slate-700 shadow-lg">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">編輯歷史</span>
        <button type="button" aria-label="關閉" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
      </div>
      {error && <p className="text-xs text-red-500">載入失敗</p>}
      {!error && versions === null && <p className="text-xs text-slate-400">載入中…</p>}
      {versions && (
        <ol className="space-y-1">
          {versions.map((v, i) => (
            <li key={i} className="border-b border-slate-100 pb-1 last:border-0">
              <p className="whitespace-pre-wrap break-words text-sm">{v.content}</p>
              <p className="text-[10px] text-slate-400">
                {new Date(v.created_at).toLocaleString()}
                {i === versions.length - 1 && '（目前）'}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Write `EditHistoryPopover` test**

`frontend/chat/src/components/EditHistoryPopover.test.tsx`：
```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EditHistoryPopover } from './EditHistoryPopover';

describe('EditHistoryPopover', () => {
  it('載入並逐版列出，最後一筆標（目前）', async () => {
    const load = vi.fn().mockResolvedValue([
      { content: '舊文', created_at: '2026-06-21T00:00:00Z' },
      { content: '新文', created_at: '2026-06-21T00:05:00Z' },
    ]);
    render(<EditHistoryPopover messageId="m1" load={load} onClose={vi.fn()} />);
    expect(await screen.findByText('舊文')).toBeInTheDocument();
    expect(screen.getByText('新文')).toBeInTheDocument();
    expect(screen.getByText(/（目前）/)).toBeInTheDocument();
  });

  it('載入失敗顯示錯誤', async () => {
    const load = vi.fn().mockRejectedValue(new Error('x'));
    render(<EditHistoryPopover messageId="m1" load={load} onClose={vi.fn()} />);
    expect(await screen.findByText('載入失敗')).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Update `Thread.tsx`**

`frontend/chat/src/components/Thread.tsx`：

(a) import：
```tsx
import { useEffect, useRef, useState } from 'react';

import Picker from '@emoji-mart/react';
import data from '@emoji-mart/data';

import { EDIT_WINDOW_MS, QUICK_REACTIONS, RESTORE_WINDOW_MS } from '../../../contracts';
import type { Attachment, MessageVersion } from '../../../contracts';
import type { ChatMessage } from '../messageStore';
import { EditHistoryPopover } from './EditHistoryPopover';
```

(b) `ThreadProps` 加：
```tsx
  onReact: (id: string, emoji: string) => void;
  onRestore: (id: string) => void;
  loadEditHistory: (id: string) => Promise<MessageVersion[]>;
  onStartCall?: () => void;
```

(c) `Thread` 解構參數加 `onRestore`、`loadEditHistory`，並在 map 渲染 `MessageBubble` 時往下傳：
```tsx
            onReact={onReact}
            onRestore={onRestore}
            loadEditHistory={loadEditHistory}
```

(d) `ReactionPicker` 換成快速 6 + 「更多表情」開 emoji-mart：
```tsx
/** 表情選擇器：快速 6 個 + 「更多表情」開 emoji-mart 完整選擇器。 */
function ReactionPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  return (
    <span className="relative">
      <button
        type="button"
        aria-label="新增表情"
        onClick={() => { setOpen((v) => !v); setFull(false); }}
        className="rounded-full px-2 py-0.5 text-xs bg-slate-100 text-slate-500 hover:bg-slate-200"
      >
        ＋
      </button>
      {open && !full && (
        <span className="absolute bottom-full left-0 z-10 mb-1 flex items-center gap-1 rounded-xl bg-white p-1 shadow-lg">
          {QUICK_REACTIONS.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => { onPick(e); setOpen(false); }}
              className="rounded px-1 hover:bg-slate-100"
            >
              {e}
            </button>
          ))}
          <button
            type="button"
            aria-label="更多表情"
            onClick={() => setFull(true)}
            className="rounded px-1 text-slate-400 hover:bg-slate-100"
          >
            ⋯
          </button>
        </span>
      )}
      {open && full && (
        <span className="absolute bottom-full left-0 z-20 mb-1">
          <Picker
            data={data}
            onEmojiSelect={(e: { native: string }) => { onPick(e.native); setOpen(false); setFull(false); }}
          />
        </span>
      )}
    </span>
  );
}
```

(e) `MessageBubble` 簽章加 `onRestore`、`loadEditHistory`，並加 `showHistory` 狀態：
```tsx
function MessageBubble({
  message, mine, isGroup, senderName, onRetry, attachmentUrl,
  currentUserId, onEdit, onDelete, onReact, onRestore, loadEditHistory,
}: {
  message: ChatMessage; mine: boolean; isGroup: boolean;
  senderName?: string; onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  currentUserId: string;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
  onRestore: (id: string) => void;
  loadEditHistory: (id: string) => Promise<MessageVersion[]>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [showHistory, setShowHistory] = useState(false);
```

(f) 已刪除分支加還原鈕（寄件人 + 5 分鐘內）：
```tsx
  if (message.deleted) {
    const canRestore =
      mine && message.deleted_at != null &&
      Date.now() - new Date(message.deleted_at).getTime() < RESTORE_WINDOW_MS;
    return (
      <div className={`flex items-center gap-2 ${mine ? 'justify-end' : 'justify-start'}`}>
        <div className="max-w-[70%] rounded-2xl bg-slate-100 px-4 py-2 text-sm italic text-slate-400">
          此訊息已刪除
        </div>
        {canRestore && (
          <button
            type="button"
            onClick={() => onRestore(message.id)}
            className="text-xs text-indigo-600 underline"
          >
            還原
          </button>
        )}
      </div>
    );
  }
```

(g) 「已編輯」標記改為可點按鈕並掛 popover（我方那段 `{message.edited_at && <span…>已編輯</span>}` 與對方那段 `{!mine && message.edited_at && …}` 都換成下面這顆共用按鈕；放在泡泡容器內、relative 定位）。把泡泡最外層 `<div className={"max-w-[70%] …"}>` 設為 `relative`，並用下列元素取代兩處「已編輯」：

我方狀態列內：
```tsx
        {mine && (
          <p className="mt-1 text-right text-xs opacity-80">
            {message.edited_at && (
              <button type="button" onClick={() => setShowHistory((v) => !v)} className="mr-1 underline opacity-70">
                已編輯
              </button>
            )}
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
        {!mine && message.edited_at && (
          <button type="button" onClick={() => setShowHistory((v) => !v)} className="mt-0.5 text-xs underline opacity-70">
            已編輯
          </button>
        )}
        {showHistory && (
          <EditHistoryPopover
            messageId={message.id}
            load={loadEditHistory}
            onClose={() => setShowHistory(false)}
          />
        )}
```
（`EditHistoryPopover` 用 `absolute`，故其容器需 `relative`——把它放在 `max-w-[70%]` 泡泡 `<div>` 內、該 div 加 `relative`。）

(h) 編輯/刪除動作列：把「編輯」與「刪除」拆開——刪除恆顯示、編輯僅時窗內顯示：
```tsx
      {/* 自己、已送達（sent）且未刪：刪除恆顯示；編輯僅 15 分鐘內 */}
      {mine && message.status === 'sent' && (
        editing ? (
          <form
            className="mt-1 flex gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              const v = draft.trim();
              if (v) onEdit(message.id, v);
              setEditing(false);
            }}
          >
            <input
              className="input text-slate-800"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="編輯訊息"
            />
            <button type="submit" className="text-xs text-indigo-600">儲存</button>
            <button type="button" onClick={() => setEditing(false)} className="text-xs text-slate-500">取消</button>
          </form>
        ) : (
          <div className="mt-0.5 flex gap-2 text-xs opacity-70">
            {Date.now() - new Date(message.created_at).getTime() < EDIT_WINDOW_MS && (
              <button
                type="button"
                onClick={() => { setDraft(message.content); setEditing(true); }}
              >
                編輯
              </button>
            )}
            <button
              type="button"
              onClick={() => onDelete(message.id)}
            >
              刪除
            </button>
          </div>
        )
      )}
```

- [ ] **Step 7: ChatApp 接線**

`frontend/chat/src/ChatApp.tsx`：

(a) 在 `toggleReaction` 之後新增：
```ts
  const restoreMessage = useCallback((id: string) => {
    socketRef.current?.send({ type: 'restore', message_id: id });
  }, []);
  const loadEditHistory = useCallback(
    (id: string) => api.getMessageEdits(id),
    [api],
  );
```

(b) `<Thread … />` 在 `onReact={toggleReaction}` 之後加兩個 props：
```tsx
          onReact={toggleReaction}
          onRestore={restoreMessage}
          loadEditHistory={loadEditHistory}
```

> 說明：`message_updated` 已涵蓋還原後的廣播（`updateMessage` 依 id upsert，把 `deleted` 翻回 false、`content` 帶回），`handleServerMessage` 不需新增 case。

- [ ] **Step 8: Run tests + typecheck**

Run（在 `frontend/chat/`）:
```
npm run test
npm run typecheck
```
Expected: 全 PASS（含既有 Thread / messageStore / store 測試與新案例）、typecheck 乾淨。

- [ ] **Step 9: Build the chat remote (MF 健全性)**

Run: `npm run build`
Expected: build 成功（emoji-mart 進 chat 包；確認無解析錯誤）。

- [ ] **Step 10: Commit**

```bash
git add frontend/chat/package.json frontend/chat/package-lock.json frontend/chat/src/components/EditHistoryPopover.tsx frontend/chat/src/components/EditHistoryPopover.test.tsx frontend/chat/src/components/Thread.tsx frontend/chat/src/components/Thread.test.tsx frontend/chat/src/ChatApp.tsx
git commit -m "[msg-actions][feat][chat] 編輯時窗/歷史、還原鈕、emoji-mart 表情選擇器"
```

---

## 收尾（全部 task 完成後）

- [ ] 後端全測：`backend/.venv/Scripts/python.exe -m pytest`（預期全綠）。
- [ ] 前端全測：`cd frontend/chat && npm run test && npm run typecheck`（預期全綠）。
- [ ] 更新 `progress.md` 與 `docs/superpowers/specs/2026-06-20-message-actions-design.md` 的「明確不做」標記（把這三項移出待辦）。
- [ ] 用 superpowers:finishing-a-development-branch 收束（合回 `feat/group-chat`）。

### E2E（手動，選配）
兩帳號跑：編輯→點「已編輯」看歷史→把 created_at 拖過 15 分鐘確認編輯鈕消失；刪除→5 分鐘內按「還原」確認雙方即時恢復；用 emoji-mart 按白名單外 emoji（如 🎉）確認雙方同步。
