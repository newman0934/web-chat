# 群組管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 補上群組的成員管理：加入/移除/退出成員、改名、admin/member 角色與權限，並用系統訊息 + WS 即時反映變更。

**Architecture:** 結構性 CRUD 走新的 REST 端點（admin 權限把關），改 DB 後寫一筆 `kind='system'` 的 Message 並透過既有 `ConnectionManager` 廣播系統訊息 + `conversation_updated`/`conversation_removed`。前端用純權限 helper + `GroupInfoPanel` 依角色顯示控制，store 處理移除/刷新。

**Tech Stack:** FastAPI、SQLAlchemy 2.0 async、Alembic、pytest + httpx + starlette TestClient；React 18 + Vite、zustand、Vitest + Testing Library。

## Global Constraints

- 不變式：**群組只要還有成員，就至少有一位 admin**。leave / remove / demote 三處共用同一判定，會讓 admin 歸零的動作回 400。
- 權限只作用於 `type='group'`；對 direct 對話呼叫成員端點 → 400。`conversation_id` 不存在或呼叫者非成員 → 404。
- 全體 admin 平權；建立者只是初始 admin，無額外特權（`creator_id` 僅作紀錄）。
- 加成員 email 路徑不需是好友（放寬原「只能加好友」）；好友快選送 `user_id`。
- 角色值域 `'admin' | 'member'`；訊息 kind 值域 `'user' | 'system'`，欄位皆 `NOT NULL` 預設分別為 `'member'` / `'user'`。
- 系統訊息：`kind='system'`、`sender_id=` 操作者、`content=` 預先組好的中文字串，照常落庫 + WS 推播。
- 後端測試走 SQLite（conftest 用 `Base.metadata.create_all`，故 model 欄位即生效）；遷移回填另用實跑 alembic 的測試驗證。
- WS DB 存取維持 `db_module.SessionLocal()` 間接層。
- Commit 標題格式 `[group-mgmt][type][scope] description`，內文結尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 系統訊息文案（逐字）：加入「{actor} 把 {target} 加入群組」、移除「{actor} 將 {target} 移出群組」、退出「{user} 退出群組」、改名「群組已改名為「{name}」」、升管理員「{actor} 將 {target} 設為管理員」、降一般成員「{actor} 取消 {target} 的管理員」。

---

### Task 1: 資料模型 + 遷移（role / kind）+ 序列化欄位

**Files:**
- Modify: `backend/app/models/conversation_member.py`（加 `role`）
- Modify: `backend/app/models/message.py`（加 `kind`）
- Create: `backend/alembic/versions/0005_member_role.py`
- Create: `backend/alembic/versions/0006_message_kind.py`
- Modify: `backend/app/schemas.py`（`MessageOut.kind`、`ConversationOut.roles`）
- Modify: `backend/app/services/conversations.py`（新增 `get_role_map`；`_build_conversation_out` 在 router，故 roles 由 router 帶入 — 見下）
- Modify: `backend/app/routers/conversations.py`（`_build_conversation_out` 帶 roles；`list_messages` 帶 kind）
- Modify: `backend/app/ws/router.py`（`_serialize_message` 帶 kind）
- Test: `backend/tests/test_migration_0005_0006.py`（新建）；`backend/tests/test_group_roles.py`（新建）

**Interfaces:**
- Produces:
  - `ConversationMember.role: str`（預設 `'member'`）、`Message.kind: str`（預設 `'user'`）
  - `MessageOut.kind: str`（預設 `'user'`）、`ConversationOut.roles: dict[uuid.UUID, str]`（預設 `{}`）
  - `get_role_map(db, conversation_id) -> dict[uuid.UUID, str]`（user_id → role）

- [ ] **Step 1: 寫遷移回填的失敗測試** — 新建 `backend/tests/test_migration_0005_0006.py`

```python
"""回歸測試：0005 把既有 group creator 回填為 admin、其餘 member；0006 訊息 kind 回填 user。
實跑 alembic（升到 0004 → 塞舊資料 → 升到 head），不重寫搬移邏輯。
"""
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"alembic upgrade {revision} failed:\n{result.stderr}"


def test_migration_backfills_role_and_kind(tmp_path):
    db = tmp_path / "mig.db"
    _alembic(db, "0004")  # 舊 schema：conversation_members 無 role、messages 無 kind

    creator = uuid.uuid4().hex
    other = uuid.uuid4().hex
    conv = uuid.uuid4().hex
    raw = sqlite3.connect(db)
    raw.execute("INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
                (creator, "c@x.com", "C", "h"))
    raw.execute("INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
                (other, "o@x.com", "O", "h"))
    raw.execute("INSERT INTO conversations (id, type, name, creator_id) VALUES (?,?,?,?)",
                (conv, "group", "G", creator))
    raw.execute("INSERT INTO conversation_members (id, conversation_id, user_id) VALUES (?,?,?)",
                (uuid.uuid4().hex, conv, creator))
    raw.execute("INSERT INTO conversation_members (id, conversation_id, user_id) VALUES (?,?,?)",
                (uuid.uuid4().hex, conv, other))
    raw.execute("INSERT INTO messages (id, conversation_id, sender_id, content) VALUES (?,?,?,?)",
                (uuid.uuid4().hex, conv, creator, "hi"))
    raw.commit()
    raw.close()

    _alembic(db, "head")

    check = sqlite3.connect(db)
    roles = dict(check.execute(
        "SELECT user_id, role FROM conversation_members WHERE conversation_id=?", (conv,)
    ).fetchall())
    assert roles[creator] == "admin"
    assert roles[other] == "member"
    kinds = [r[0] for r in check.execute("SELECT kind FROM messages").fetchall()]
    assert kinds == ["user"]
    check.close()
```

- [ ] **Step 2: 跑測試確認失敗**

Run（於 `backend/`）: `.venv/Scripts/python.exe -m pytest tests/test_migration_0005_0006.py -v`
Expected: FAIL — `alembic upgrade head` 找不到 0005/0006（或無 role/kind 欄位）。

- [ ] **Step 3: 加 model 欄位**

`backend/app/models/conversation_member.py`：import 行改為含 `String`，並在 `created_at` 之前加 `role`：

```python
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
```
```python
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default="member"
    )
```

`backend/app/models/message.py`：import 行改為含 `String`，並在 `deleted_at` 之後加 `kind`：

```python
from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
```
```python
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user", server_default="user"
    )
```

- [ ] **Step 4: 寫兩支遷移**

`backend/alembic/versions/0005_member_role.py`：

```python
"""conversation_members.role + backfill group creators as admin

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_members",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
    )
    # 群組建立者回填為 admin（關聯 conversations.creator_id == members.user_id）
    op.execute(
        """
        UPDATE conversation_members
        SET role='admin'
        WHERE conversation_id IN (
            SELECT id FROM conversations
            WHERE type='group' AND creator_id = conversation_members.user_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("conversation_members", "role")
```

`backend/alembic/versions/0006_message_kind.py`：

```python
"""messages.kind ('user'|'system')

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="user"),
    )


def downgrade() -> None:
    op.drop_column("messages", "kind")
```

- [ ] **Step 5: 跑遷移測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_migration_0005_0006.py -v`
Expected: PASS。

- [ ] **Step 6: 加 schema 欄位與序列化、`get_role_map`**

`backend/app/schemas.py`：`MessageOut` 加（接在 `reactions` 後）：

```python
    kind: str = "user"
```

`ConversationOut` 加（接在 `unread_count` 後）：

```python
    roles: dict[uuid.UUID, str] = Field(default_factory=dict)
```

`backend/app/services/conversations.py`：在檔末新增：

```python
async def get_role_map(db: AsyncSession, conversation_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """回傳該對話 user_id → role 對照。"""
    rows = await db.execute(
        select(ConversationMember.user_id, ConversationMember.role).where(
            ConversationMember.conversation_id == conversation_id
        )
    )
    return {uid: role for uid, role in rows.all()}
```

`backend/app/routers/conversations.py`：`_build_conversation_out` 內，在 `return ConversationOut(` 前取得 roles，並在建構 `ConversationOut(...)` 加 `roles=`、`last_message` 的 `MessageOut(...)` 加 `kind=last.kind`：

```python
    from app.services.conversations import get_role_map  # 與其他 import 並列亦可
    roles = await get_role_map(db, conv.id)
```
把 `last_out = MessageOut(... read_count=await read_count(db, last.id))` 改成多帶一行 `kind=last.kind,`；並在 `return ConversationOut(...)` 尾端加 `roles=roles,`。

`list_messages` 內建構 `MessageOut(...)` 處加 `kind=m.kind,`。

`backend/app/ws/router.py`：`_serialize_message` 回傳 dict 末尾加 `"kind": msg.kind,`。

- [ ] **Step 7: 寫 roles 整合測試** — 新建 `backend/tests/test_group_roles.py`

```python
import pytest

pytestmark = pytest.mark.asyncio


async def _make_group(client, register_user, auth_headers):
    alice = await register_user("gra@example.com", "Alice")
    bob = await register_user("grb@example.com", "Bob")
    await client.post("/contacts", json={"email": "grb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]},
            headers=auth_headers(alice))).json()
    return alice, bob, aid, bid, conv


async def test_conversation_lists_roles_creator_admin(client, register_user, auth_headers):
    alice, bob, aid, bid, conv = await _make_group(client, register_user, auth_headers)
    assert conv["roles"][aid] == "admin"
    assert conv["roles"][bid] == "member"
    convs = (await client.get("/conversations", headers=auth_headers(bob))).json()
    g = next(c for c in convs if c["id"] == conv["id"])
    assert g["roles"][aid] == "admin" and g["roles"][bid] == "member"
```

- [ ] **Step 8: 跑全套後端測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 全綠（既有 58 + 本檔新測試）。

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/conversation_member.py backend/app/models/message.py \
  backend/alembic/versions/0005_member_role.py backend/alembic/versions/0006_message_kind.py \
  backend/app/schemas.py backend/app/services/conversations.py \
  backend/app/routers/conversations.py backend/app/ws/router.py \
  backend/tests/test_migration_0005_0006.py backend/tests/test_group_roles.py
git commit -m "[group-mgmt][feat][backend] ConversationMember.role + Message.kind + roles 序列化

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 成員服務 helper + 加入/移除 REST + 系統訊息 + WS 廣播

**Files:**
- Modify: `backend/app/services/conversations.py`（`get_member`、`is_group_admin`、`create_system_message`、`would_leave_groupless_of_admin`）
- Modify: `backend/app/schemas.py`（`AddMemberRequest`）
- Modify: `backend/app/routers/conversations.py`（廣播 helper + POST/DELETE members 端點）
- Test: `backend/tests/test_group_members.py`（新建）

**Interfaces:**
- Consumes: `get_role_map`（Task 1）、`get_member_ids`、`get_conversation_for_member`、`manager`。
- Produces:
  - `get_member(db, conv_id, user_id) -> ConversationMember | None`
  - `is_group_admin(db, conv_id, user_id) -> bool`
  - `create_system_message(db, conv_id, sender_id, content) -> Message`
  - `would_leave_groupless_of_admin(db, conv_id, user_id, *, removing=False, new_role=None) -> bool`
  - router 私有廣播 helper：`_system_message_payload(msg)`、`_push_system_and_updated(member_ids, conv_id, payload)`、`_push_removed(user_ids, conv_id)`（Task 3 共用）
  - 端點：`POST /conversations/{id}/members`、`DELETE /conversations/{id}/members/{user_id}`，皆回 `ConversationOut`

- [ ] **Step 1: 寫失敗測試** — 新建 `backend/tests/test_group_members.py`

```python
import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _make_group(client, register_user, auth_headers):
    alice = await register_user("gma@example.com", "Alice")
    bob = await register_user("gmb@example.com", "Bob")
    await client.post("/contacts", json={"email": "gmb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]},
            headers=auth_headers(alice))).json()
    return alice, bob, aid, bid, conv["id"]


async def test_admin_adds_member_by_email_nonfriend(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    # carol 非 alice 好友
    await register_user("gmc@example.com", "Carol")
    resp = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "gmc@example.com"}, headers=auth_headers(alice))
    assert resp.status_code == 200, resp.text
    cid = (await client.get("/users/me", headers=auth_headers(await register_user("gmc2@example.com", "X")))).json()  # noqa: not used
    body = resp.json()
    emails = {m["email"] for m in body["members"]}
    assert "gmc@example.com" in emails
    # 系統訊息落庫
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert any(m["kind"] == "system" and "加入群組" in m["content"] for m in msgs)


async def test_add_member_by_user_id(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    carol = await register_user("gmc3@example.com", "Carol")
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    resp = await client.post(f"/conversations/{conv_id}/members",
            json={"user_id": cid}, headers=auth_headers(alice))
    assert resp.status_code == 200
    assert resp.json()["roles"][cid] == "member"


async def test_add_member_errors(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    # 非 admin（bob）加人 → 403
    r1 = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "gmb@example.com"}, headers=auth_headers(bob))
    assert r1.status_code == 403
    # 已是成員 → 400
    r2 = await client.post(f"/conversations/{conv_id}/members",
            json={"user_id": bid}, headers=auth_headers(alice))
    assert r2.status_code == 400
    # 查無 email → 404
    r3 = await client.post(f"/conversations/{conv_id}/members",
            json={"email": "nobody@example.com"}, headers=auth_headers(alice))
    assert r3.status_code == 404


async def test_admin_removes_member(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    resp = await client.request("DELETE", f"/conversations/{conv_id}/members/{bid}",
            headers=auth_headers(alice))
    assert resp.status_code == 200
    assert bid not in resp.json()["roles"]
    # 不能移自己
    r2 = await client.request("DELETE", f"/conversations/{conv_id}/members/{aid}",
            headers=auth_headers(alice))
    assert r2.status_code == 400


async def test_add_member_broadcasts_ws(client, register_user, auth_headers):
    alice, bob, aid, bid, conv_id = await _make_group(client, register_user, auth_headers)
    carol = await register_user("gmd@example.com", "Carol")
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as ws_bob:
            await client.post(f"/conversations/{conv_id}/members",
                    json={"user_id": cid}, headers=auth_headers(alice))
            seen = {ws_bob.receive_json()["type"] for _ in range(2)}
            assert "message" in seen and "conversation_updated" in seen
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_members.py -v`
Expected: FAIL — 端點不存在（404/405）。

- [ ] **Step 3: 加服務 helper**

`backend/app/services/conversations.py` 檔末新增：

```python
async def get_member(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> ConversationMember | None:
    res = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    return res.scalar_one_or_none()


async def is_group_admin(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    m = await get_member(db, conversation_id, user_id)
    return m is not None and m.role == "admin"


async def create_system_message(
    db: AsyncSession, conversation_id: uuid.UUID, sender_id: uuid.UUID, content: str
) -> Message:
    msg = Message(
        conversation_id=conversation_id, sender_id=sender_id, content=content, kind="system"
    )
    db.add(msg)
    await db.flush()
    return msg


async def would_leave_groupless_of_admin(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    removing: bool = False,
    new_role: str | None = None,
) -> bool:
    """模擬把 user_id 移除 / 改成 new_role 後，群組是否仍有成員卻 0 個 admin。"""
    role_map = await get_role_map(db, conversation_id)
    if removing:
        role_map.pop(user_id, None)
    elif new_role is not None:
        role_map[user_id] = new_role
    if not role_map:
        return False  # 群空交由刪群邏輯處理
    return not any(r == "admin" for r in role_map.values())
```

- [ ] **Step 4: 加 schema**

`backend/app/schemas.py` 加（在 `GroupCreateRequest` 後）：

```python
class AddMemberRequest(BaseModel):
    user_id: uuid.UUID | None = None
    email: EmailStr | None = None
```

- [ ] **Step 5: 加廣播 helper 與端點**

`backend/app/routers/conversations.py`：import 區補上（與既有並列）：

```python
from datetime import timezone
from app.ws.manager import manager
from app.models import Contact, Conversation, ConversationMember, Message, User  # 已有，確認含 ConversationMember/Message
from app.schemas import AddMemberRequest
from app.services.conversations import (
    create_system_message,
    get_member,
    get_role_map,
    is_group_admin,
    would_leave_groupless_of_admin,
)
```

新增模組級 helper 與兩個端點（放在 `list_messages` 之後）：

```python
def _system_message_payload(msg: Message) -> dict:
    """系統訊息的 WS payload（不觸發 ORM lazy-load，欄位皆已知）。"""
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": msg.content,
        "created_at": msg.created_at.astimezone(timezone.utc).isoformat(),
        "read_count": 0,
        "attachment": None,
        "edited_at": None,
        "deleted": False,
        "reactions": [],
        "kind": "system",
    }


async def _push_system_and_updated(member_ids, conversation_id, payload) -> None:
    for rid in member_ids:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})
            await manager.send_to_user(
                rid, {"type": "conversation_updated", "conversation_id": str(conversation_id)}
            )


async def _push_removed(user_ids, conversation_id) -> None:
    for rid in user_ids:
        if manager.is_online(rid):
            await manager.send_to_user(
                rid, {"type": "conversation_removed", "conversation_id": str(conversation_id)}
            )


async def _require_group_admin(db, conversation_id, user) -> Conversation:
    """共用守門：對話存在且呼叫者是成員、是 group、且呼叫者為 admin。"""
    conv = await get_conversation_for_member(db, conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="僅群組可管理成員")
    if not await is_group_admin(db, conversation_id, user.id):
        raise HTTPException(status_code=403, detail="僅管理員可執行此操作")
    return conv


@router.post("/{conversation_id}/members", response_model=ConversationOut)
async def add_member(
    conversation_id: uuid.UUID,
    payload: AddMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    if payload.user_id is not None:
        target = await db.get(User, payload.user_id)
    elif payload.email is not None:
        res = await db.execute(select(User).where(User.email == payload.email))
        target = res.scalar_one_or_none()
    else:
        raise HTTPException(status_code=400, detail="需提供 user_id 或 email")
    if target is None:
        raise HTTPException(status_code=404, detail="查無此使用者")
    if await get_member(db, conversation_id, target.id) is not None:
        raise HTTPException(status_code=400, detail="此人已是群組成員")

    db.add(ConversationMember(conversation_id=conversation_id, user_id=target.id, role="member"))
    sys = await create_system_message(
        db, conversation_id, current_user.id,
        f"{current_user.display_name} 把 {target.display_name} 加入群組",
    )
    await db.commit()
    await db.refresh(sys)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    await db.refresh(conv)
    return await _build_conversation_out(db, conv, current_user)


@router.delete("/{conversation_id}/members/{user_id}", response_model=ConversationOut)
async def remove_member(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能移除自己，請用退出群組")
    target_member = await get_member(db, conversation_id, user_id)
    if target_member is None:
        raise HTTPException(status_code=404, detail="此人不是群組成員")
    if await would_leave_groupless_of_admin(db, conversation_id, user_id, removing=True):
        raise HTTPException(status_code=400, detail="群組需至少一位管理員")

    target = await db.get(User, user_id)
    member_ids_before = await get_member_ids(db, conversation_id)
    await db.delete(target_member)
    sys = await create_system_message(
        db, conversation_id, current_user.id,
        f"{current_user.display_name} 將 {target.display_name} 移出群組",
    )
    await db.commit()
    await db.refresh(sys)

    remaining = [m for m in member_ids_before if m != user_id]
    await _push_system_and_updated(remaining, conversation_id, _system_message_payload(sys))
    await _push_removed([user_id], conversation_id)
    await db.refresh(conv)
    return await _build_conversation_out(db, conv, current_user)
```

> 註：`remove_member` 的 admin 不變式實際上不會觸發（操作者本身是 admin 且未被移除），保留檢查以滿足規格一致性。

- [ ] **Step 6: 跑測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_members.py -v`
Expected: PASS（含 WS 廣播測試）。

- [ ] **Step 7: 跑全套確認無回歸**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 全綠。

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversations.py backend/app/schemas.py \
  backend/app/routers/conversations.py backend/tests/test_group_members.py
git commit -m "[group-mgmt][feat][backend] 加入/移除成員 REST + 系統訊息 + WS 廣播

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 退出 / 改名 / 角色 REST + 不變式

**Files:**
- Modify: `backend/app/schemas.py`（`GroupRenameRequest`、`RoleUpdateRequest`）
- Modify: `backend/app/routers/conversations.py`（POST leave、PATCH rename、PATCH role）
- Test: `backend/tests/test_group_admin_ops.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `_require_group_admin`、`_push_system_and_updated`、`_push_removed`、`_system_message_payload`、`create_system_message`、`would_leave_groupless_of_admin`、`get_member`、`get_member_ids`、`get_conversation_for_member`。
- Produces：`POST /conversations/{id}/leave`（回 `{"ok": true}`）、`PATCH /conversations/{id}`、`PATCH /conversations/{id}/members/{user_id}/role`（後兩者回 `ConversationOut`）。

- [ ] **Step 1: 寫失敗測試** — 新建 `backend/tests/test_group_admin_ops.py`

```python
import pytest

pytestmark = pytest.mark.asyncio


async def _trio_group(client, register_user, auth_headers):
    alice = await register_user("aoa@example.com", "Alice")
    bob = await register_user("aob@example.com", "Bob")
    carol = await register_user("aoc@example.com", "Carol")
    for em in ("aob@example.com", "aoc@example.com"):
        await client.post("/contacts", json={"email": em}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    cid = (await client.get("/users/me", headers=auth_headers(carol))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid, cid]},
            headers=auth_headers(alice))).json()
    return (alice, bob, carol), (aid, bid, cid), conv["id"]


async def test_rename_group(client, register_user, auth_headers):
    (alice, *_), _, conv_id = await _trio_group(client, register_user, auth_headers)
    resp = await client.patch(f"/conversations/{conv_id}", json={"name": "新名字"},
            headers=auth_headers(alice))
    assert resp.status_code == 200 and resp.json()["name"] == "新名字"
    msgs = (await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))).json()
    assert any(m["kind"] == "system" and "改名為" in m["content"] for m in msgs)


async def test_promote_and_demote(client, register_user, auth_headers):
    (alice, bob, carol), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    up = await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "admin"}, headers=auth_headers(alice))
    assert up.status_code == 200 and up.json()["roles"][bid] == "admin"
    down = await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "member"}, headers=auth_headers(alice))
    assert down.json()["roles"][bid] == "member"


async def test_cannot_demote_last_admin(client, register_user, auth_headers):
    (alice, *_), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    resp = await client.patch(f"/conversations/{conv_id}/members/{aid}/role",
            json={"role": "member"}, headers=auth_headers(alice))
    assert resp.status_code == 400


async def test_leave_blocks_last_admin_then_succeeds_after_promote(client, register_user, auth_headers):
    (alice, bob, carol), (aid, bid, cid), conv_id = await _trio_group(client, register_user, auth_headers)
    blocked = await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    assert blocked.status_code == 400
    await client.patch(f"/conversations/{conv_id}/members/{bid}/role",
            json={"role": "admin"}, headers=auth_headers(alice))
    ok = await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    assert ok.status_code == 200
    # alice 已非成員
    convs = (await client.get("/conversations", headers=auth_headers(alice))).json()
    assert all(c["id"] != conv_id for c in convs)


async def test_last_member_leave_deletes_group(client, register_user, auth_headers):
    alice = await register_user("aolone@example.com", "Alice")
    bob = await register_user("aolone2@example.com", "Bob")
    await client.post("/contacts", json={"email": "aolone2@example.com"}, headers=auth_headers(alice))
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    conv = (await client.post("/conversations/groups",
            json={"name": "G", "member_user_ids": [bid]}, headers=auth_headers(alice))).json()
    conv_id = conv["id"]
    # bob 退出（alice 是唯一 admin，bob 是 member）
    await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(bob))
    # alice 此時是最後一人，退出 → 刪群
    await client.post(f"/conversations/{conv_id}/leave", headers=auth_headers(alice))
    # 對話應已不存在
    msgs = await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(alice))
    assert msgs.status_code == 404
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_admin_ops.py -v`
Expected: FAIL — 端點不存在。

- [ ] **Step 3: 加 schema**

`backend/app/schemas.py`：頂部 import 加 `from typing import Literal`（若尚無）。新增（在 `AddMemberRequest` 後）：

```python
class GroupRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class RoleUpdateRequest(BaseModel):
    role: Literal["admin", "member"]
```

`backend/app/routers/conversations.py` import 補 `GroupRenameRequest, RoleUpdateRequest`。

- [ ] **Step 4: 加三個端點**

`backend/app/routers/conversations.py`（接在 `remove_member` 之後）：

```python
@router.post("/{conversation_id}/leave")
async def leave_group(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_for_member(db, conversation_id, current_user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="查無此對話或無權限")
    if conv.type != "group":
        raise HTTPException(status_code=400, detail="僅群組可退出")

    member_ids_before = await get_member_ids(db, conversation_id)
    me_member = await get_member(db, conversation_id, current_user.id)

    if len(member_ids_before) == 1:
        # 最後一人退出 → 刪群（成員/訊息 CASCADE）
        await db.delete(conv)
        await db.commit()
        await _push_removed([current_user.id], conversation_id)
        return {"ok": True}

    if await would_leave_groupless_of_admin(db, conversation_id, current_user.id, removing=True):
        raise HTTPException(status_code=400, detail="請先指派另一位管理員再退出")

    await db.delete(me_member)
    sys = await create_system_message(
        db, conversation_id, current_user.id, f"{current_user.display_name} 退出群組"
    )
    await db.commit()
    await db.refresh(sys)

    remaining = [m for m in member_ids_before if m != current_user.id]
    await _push_system_and_updated(remaining, conversation_id, _system_message_payload(sys))
    await _push_removed([current_user.id], conversation_id)
    return {"ok": True}


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_group(
    conversation_id: uuid.UUID,
    payload: GroupRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    conv.name = payload.name.strip()
    sys = await create_system_message(
        db, conversation_id, current_user.id, f"群組已改名為「{conv.name}」"
    )
    await db.commit()
    await db.refresh(sys)
    await db.refresh(conv)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    return await _build_conversation_out(db, conv, current_user)


@router.patch("/{conversation_id}/members/{user_id}/role", response_model=ConversationOut)
async def set_member_role(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await _require_group_admin(db, conversation_id, current_user)
    target_member = await get_member(db, conversation_id, user_id)
    if target_member is None:
        raise HTTPException(status_code=404, detail="此人不是群組成員")
    if target_member.role == payload.role:
        # no-op：不寫系統訊息，直接回現況
        return await _build_conversation_out(db, conv, current_user)
    if payload.role == "member" and await would_leave_groupless_of_admin(
        db, conversation_id, user_id, new_role="member"
    ):
        raise HTTPException(status_code=400, detail="群組需至少一位管理員")

    target = await db.get(User, user_id)
    target_member.role = payload.role
    text = (
        f"{current_user.display_name} 將 {target.display_name} 設為管理員"
        if payload.role == "admin"
        else f"{current_user.display_name} 取消 {target.display_name} 的管理員"
    )
    sys = await create_system_message(db, conversation_id, current_user.id, text)
    await db.commit()
    await db.refresh(sys)

    member_ids = await get_member_ids(db, conversation_id)
    await _push_system_and_updated(member_ids, conversation_id, _system_message_payload(sys))
    await db.refresh(conv)
    return await _build_conversation_out(db, conv, current_user)
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_admin_ops.py -v`
Expected: PASS。

- [ ] **Step 6: 跑全套確認無回歸**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 全綠。

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/conversations.py \
  backend/tests/test_group_admin_ops.py
git commit -m "[group-mgmt][feat][backend] 退出/改名/角色 REST + 至少一位 admin 不變式

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: contracts + ApiClient + 純權限 helper

**Files:**
- Modify: `frontend/contracts/index.ts`（`Message.kind`、`ConversationOut.roles`、WS 事件）
- Modify: `frontend/chat/src/api.ts`（五個成員操作方法）
- Create: `frontend/chat/src/groupPermissions.ts`
- Test: `frontend/chat/src/groupPermissions.test.ts`

**Interfaces:**
- Produces：
  - contracts：`Message.kind?: 'user' | 'system'`、`Conversation.roles: Record<string, 'admin' | 'member'>`、`ServerWsMessage` 加 `conversation_updated` / `conversation_removed`。
  - `ApiClient.addMember/removeMember/leaveGroup/renameGroup/setMemberRole`。
  - `groupPermissions`：`isAdmin(roles, userId)`、`adminCount(roles)`、`isLastAdmin(roles, userId)`。

- [ ] **Step 1: 寫失敗測試** — 新建 `frontend/chat/src/groupPermissions.test.ts`

```typescript
import { describe, expect, it } from 'vitest';

import { adminCount, isAdmin, isLastAdmin } from './groupPermissions';

const roles = { a: 'admin', b: 'member', c: 'admin' } as Record<string, 'admin' | 'member'>;

describe('groupPermissions', () => {
  it('isAdmin', () => {
    expect(isAdmin(roles, 'a')).toBe(true);
    expect(isAdmin(roles, 'b')).toBe(false);
    expect(isAdmin(roles, 'zzz')).toBe(false);
  });
  it('adminCount', () => {
    expect(adminCount(roles)).toBe(2);
    expect(adminCount({ a: 'member' })).toBe(0);
  });
  it('isLastAdmin', () => {
    expect(isLastAdmin({ a: 'admin', b: 'member' }, 'a')).toBe(true);
    expect(isLastAdmin(roles, 'a')).toBe(false); // 兩位 admin
    expect(isLastAdmin(roles, 'b')).toBe(false); // 非 admin
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/groupPermissions.test.ts`
Expected: FAIL — `Cannot find module './groupPermissions'`。

- [ ] **Step 3: 實作 `groupPermissions.ts`**

```typescript
// 群組角色純權限判定（不碰 React / 網路），單獨單元測試。

export type Role = 'admin' | 'member';
export type RoleMap = Record<string, Role>;

/** userId 是否為該群 admin。 */
export function isAdmin(roles: RoleMap, userId: string): boolean {
  return roles[userId] === 'admin';
}

/** 群內 admin 人數。 */
export function adminCount(roles: RoleMap): number {
  return Object.values(roles).filter((r) => r === 'admin').length;
}

/** userId 是否為唯一的 admin（移除/降級會使群組無 admin）。 */
export function isLastAdmin(roles: RoleMap, userId: string): boolean {
  return isAdmin(roles, userId) && adminCount(roles) === 1;
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/groupPermissions.test.ts`
Expected: 3 passed。

- [ ] **Step 5: 擴充 contracts**

`frontend/contracts/index.ts`：
- `Message` 介面加（在 `reactions` 後）：`kind?: 'user' | 'system';`
- `Conversation` 介面加（在 `unread_count` 後）：`roles: Record<string, 'admin' | 'member'>;`
- `ServerWsMessage` 聯集尾端加：

```typescript
  | { type: 'conversation_updated'; conversation_id: string }
  | { type: 'conversation_removed'; conversation_id: string };
```

- [ ] **Step 6: 加 ApiClient 方法**

`frontend/chat/src/api.ts`：在 `uploadFile` 之前加入：

```typescript
  /** 加成員（user_id 好友快選 或 email 加非好友）。回更新後的 Conversation。 */
  addMember(conversationId: string, opts: { userId?: string; email?: string }) {
    return this.req<Conversation>(`/conversations/${conversationId}/members`, {
      method: 'POST',
      body: JSON.stringify({ user_id: opts.userId, email: opts.email }),
    });
  }

  /** 移除成員（admin）。回更新後的 Conversation。 */
  removeMember(conversationId: string, userId: string) {
    return this.req<Conversation>(`/conversations/${conversationId}/members/${userId}`, {
      method: 'DELETE',
    });
  }

  /** 退出群組。 */
  leaveGroup(conversationId: string) {
    return this.req<{ ok: boolean }>(`/conversations/${conversationId}/leave`, {
      method: 'POST',
    });
  }

  /** 群組改名（admin）。 */
  renameGroup(conversationId: string, name: string) {
    return this.req<Conversation>(`/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }

  /** 設定成員角色（admin）。 */
  setMemberRole(conversationId: string, userId: string, role: 'admin' | 'member') {
    return this.req<Conversation>(`/conversations/${conversationId}/members/${userId}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    });
  }
```

- [ ] **Step 7: 跑 chat typecheck**

Run: `cd frontend/chat && npm run typecheck`
Expected: 乾淨（`Conversation.roles` 為必填——既有建構 Conversation 的測試 fixture 若報錯，於 Task 5/7 對應測試檔補上 `roles: {}`；本任務只新增 helper 測試與型別，現有 chat 程式碼不建構 Conversation 物件，故應乾淨）。

- [ ] **Step 8: Commit**

```bash
git add frontend/contracts/index.ts frontend/chat/src/api.ts \
  frontend/chat/src/groupPermissions.ts frontend/chat/src/groupPermissions.test.ts
git commit -m "[group-mgmt][feat][chat] contracts/ApiClient 成員操作 + 純權限 helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: store 移除對話 + ChatApp WS 路由

**Files:**
- Modify: `frontend/chat/src/store.ts`（`removeConversation` action）
- Modify: `frontend/chat/src/ChatApp.tsx`（路由 `conversation_updated` / `conversation_removed`）
- Test: `frontend/chat/src/store.test.ts`（加 `removeConversation` 測試）

**Interfaces:**
- Consumes：`ServerWsMessage` 的 `conversation_updated` / `conversation_removed`（Task 4）。
- Produces：`useChatStore` 新增 `removeConversation(conversationId: string)`。

- [ ] **Step 1: 寫失敗測試** — 在 `frontend/chat/src/store.test.ts` 末尾加入

```typescript
import { describe, expect, it, beforeEach } from 'vitest';
import { useChatStore } from './store';
import type { Conversation } from '../../contracts';

function conv(id: string): Conversation {
  return {
    id, type: 'group', name: 'G', other_user: null, members: [],
    last_message: null, unread_count: 0, roles: {},
  };
}

describe('removeConversation', () => {
  beforeEach(() => useChatStore.getState().reset());

  it('移除對話並清掉其訊息；若為 active 則清空 activeId', () => {
    const st = useChatStore.getState();
    st.setConversations([conv('c1'), conv('c2')]);
    st.loadHistory('c1', []);
    st.setActiveId('c1');
    st.removeConversation('c1');
    const s = useChatStore.getState();
    expect(s.conversations.map((c) => c.id)).toEqual(['c2']);
    expect(s.messages['c1']).toBeUndefined();
    expect(s.activeId).toBeNull();
  });

  it('移除非 active 對話不動 activeId', () => {
    const st = useChatStore.getState();
    st.setConversations([conv('c1'), conv('c2')]);
    st.setActiveId('c2');
    st.removeConversation('c1');
    expect(useChatStore.getState().activeId).toBe('c2');
  });
});
```

> 註：若既有 `store.test.ts` 已有建立 `Conversation` 的 fixture，請在那些物件補 `roles: {}` 讓型別通過。

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/store.test.ts`
Expected: FAIL — `removeConversation` 不存在。

- [ ] **Step 3: 加 store action**

`frontend/chat/src/store.ts`：`ChatState` 介面在 `reset` 前加宣告：

```typescript
  /** 移除某對話（被踢/退出/群解散）；清掉其訊息與 hasMore，若為 active 則切回空畫面。 */
  removeConversation: (conversationId: string) => void;
```

實作（在 `reset` 前）：

```typescript
  removeConversation: (conversationId) =>
    set((s) => {
      const messages = { ...s.messages };
      delete messages[conversationId];
      const hasMore = { ...s.hasMore };
      delete hasMore[conversationId];
      return {
        conversations: s.conversations.filter((c) => c.id !== conversationId),
        messages,
        hasMore,
        activeId: s.activeId === conversationId ? null : s.activeId,
      };
    }),
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/store.test.ts`
Expected: PASS。

- [ ] **Step 5: ChatApp 路由新 WS 事件**

`frontend/chat/src/ChatApp.tsx`：`handleServerMessage` 的 `switch` 內，於 `default:` 前加入：

```typescript
        case 'conversation_updated':
          void loadConversations();
          break;
        case 'conversation_removed':
          st.removeConversation(msg.conversation_id);
          break;
```

（`st` 即該函式開頭的 `const st = useChatStore.getState();`，`loadConversations` 已在 deps。）

- [ ] **Step 6: 跑 chat 測試與 typecheck**

Run: `cd frontend/chat && npx vitest run && npm run typecheck`
Expected: 全綠、tsc 乾淨。

- [ ] **Step 7: Commit**

```bash
git add frontend/chat/src/store.ts frontend/chat/src/ChatApp.tsx frontend/chat/src/store.test.ts
git commit -m "[group-mgmt][feat][chat] store removeConversation + ChatApp 路由群組事件

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Thread 系統訊息渲染

**Files:**
- Modify: `frontend/chat/src/components/Thread.tsx`（`MessageBubble` 處理 `kind==='system'`）
- Test: `frontend/chat/src/components/Thread.test.tsx`（加系統訊息渲染測試）

**Interfaces:**
- Consumes：`Message.kind`（Task 4）。`ChatMessage` 已 extends `Message`，故帶 `kind`。

- [ ] **Step 1: 寫失敗測試** — 在 `frontend/chat/src/components/Thread.test.tsx` 加入一個案例

於檔內既有 render 輔助風格，新增：

```tsx
it('系統訊息置中渲染、無泡泡動作', () => {
  const sys = {
    id: 's1', conversation_id: 'c1', sender_id: 'u-actor',
    content: 'Alice 把 Bob 加入群組', created_at: new Date().toISOString(),
    read_count: 0, attachment: null, edited_at: null, deleted: false,
    reactions: [], kind: 'system' as const, status: 'sent' as const,
  };
  render(
    <Thread
      title="G" isGroup memberNames={{}} messages={[sys]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={() => {}} onSend={() => {}} onRetry={() => {}}
      attachmentUrl={() => ''} onUpload={async () => null}
      onEdit={() => {}} onDelete={() => {}} onReact={() => {}}
    />,
  );
  expect(screen.getByText('Alice 把 Bob 加入群組')).toBeInTheDocument();
  // 系統訊息不應出現「編輯 / 刪除」泡泡動作
  expect(screen.queryByRole('button', { name: '編輯' })).toBeNull();
});
```

（若既有測試的 import / render 方式不同，沿用該檔現有 helper；關鍵是傳入 `kind: 'system'` 的訊息並斷言置中文字與無編輯鈕。）

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: FAIL — 目前系統訊息會被當一般泡泡渲染（內容仍在，但會帶泡泡結構；本測試聚焦在「置中且無動作」，先確認紅燈或行為不符）。

- [ ] **Step 3: 在 MessageBubble 加系統訊息分支**

`frontend/chat/src/components/Thread.tsx`：`MessageBubble` 函式內最前面（在 `if (message.deleted)` 之前）加入：

```tsx
  // 系統訊息：置中灰字一行，無泡泡 / 狀態 / 編輯刪除 / 表情。
  if (message.kind === 'system') {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
          {message.content}
        </span>
      </div>
    );
  }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/components/Thread.tsx frontend/chat/src/components/Thread.test.tsx
git commit -m "[group-mgmt][feat][chat] Thread 系統訊息置中渲染

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: GroupInfoPanel + ChatApp 接線 + 文件

**Files:**
- Create: `frontend/chat/src/components/GroupInfoPanel.tsx`
- Test: `frontend/chat/src/components/GroupInfoPanel.test.tsx`
- Modify: `frontend/chat/src/components/Thread.tsx`（header 加「群組資訊」鈕）
- Modify: `frontend/chat/src/ChatApp.tsx`（掛 panel、接 ApiClient）
- Modify: `progress.md`、`docs/superpowers/specs/2026-06-19-group-chat-design.md`（標記四項完成）

**Interfaces:**
- Consumes：`groupPermissions.isAdmin`（Task 4）、`ApiClient` 成員方法（Task 4）、`Conversation.roles`、`Contact`。
- Produces：
  - `GroupInfoPanel` props：`{ conversation: Conversation; currentUserId: string; contacts: Contact[]; onAddMember(opts:{userId?:string;email?:string}): void; onRemoveMember(userId:string): void; onSetRole(userId:string, role:'admin'|'member'): void; onRename(name:string): void; onLeave(): void; onClose(): void }`
  - Thread 新增 prop：`onShowGroupInfo?: () => void`

- [ ] **Step 1: 寫失敗測試** — 新建 `frontend/chat/src/components/GroupInfoPanel.test.tsx`

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GroupInfoPanel } from './GroupInfoPanel';
import type { Conversation } from '../../../contracts';

function makeConv(roles: Record<string, 'admin' | 'member'>): Conversation {
  return {
    id: 'c1', type: 'group', name: 'G', other_user: null,
    members: [
      { id: 'a', email: 'a@x.com', display_name: 'Alice' },
      { id: 'b', email: 'b@x.com', display_name: 'Bob' },
    ],
    last_message: null, unread_count: 0, roles,
  };
}

const handlers = {
  contacts: [], onAddMember: vi.fn(), onRemoveMember: vi.fn(),
  onSetRole: vi.fn(), onRename: vi.fn(), onLeave: vi.fn(), onClose: vi.fn(),
};

describe('GroupInfoPanel', () => {
  it('admin 看到改名與管理控制', () => {
    render(<GroupInfoPanel conversation={makeConv({ a: 'admin', b: 'member' })} currentUserId="a" {...handlers} />);
    expect(screen.getByLabelText('群組名稱')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '移除 Bob' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '退出群組' })).toBeInTheDocument();
  });

  it('一般成員只見唯讀成員列與退出', () => {
    render(<GroupInfoPanel conversation={makeConv({ a: 'admin', b: 'member' })} currentUserId="b" {...handlers} />);
    expect(screen.queryByLabelText('群組名稱')).toBeNull();
    expect(screen.queryByRole('button', { name: '移除 Alice' })).toBeNull();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '退出群組' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/GroupInfoPanel.test.tsx`
Expected: FAIL — `Cannot find module './GroupInfoPanel'`。

- [ ] **Step 3: 實作 `GroupInfoPanel.tsx`**

```tsx
// 群組資訊面板：成員列 + 角色徽章；admin 可改名/加人/移除/升降/退出，一般成員只見唯讀+退出。

import { useState } from 'react';

import type { Contact, Conversation } from '../../../contracts';
import { isAdmin } from '../groupPermissions';

interface Props {
  conversation: Conversation;
  currentUserId: string;
  contacts: Contact[];
  onAddMember: (opts: { userId?: string; email?: string }) => void;
  onRemoveMember: (userId: string) => void;
  onSetRole: (userId: string, role: 'admin' | 'member') => void;
  onRename: (name: string) => void;
  onLeave: () => void;
  onClose: () => void;
}

/** 群組資訊 / 成員管理面板（側拉）。 */
export function GroupInfoPanel({
  conversation, currentUserId, contacts,
  onAddMember, onRemoveMember, onSetRole, onRename, onLeave, onClose,
}: Props) {
  const admin = isAdmin(conversation.roles, currentUserId);
  const [name, setName] = useState(conversation.name ?? '');
  const [email, setEmail] = useState('');
  // 尚未在群內的好友（可快選加入）
  const memberIds = new Set(conversation.members.map((m) => m.id));
  const addableFriends = contacts.filter((c) => !memberIds.has(c.user_id));

  return (
    <aside className="flex h-full w-80 flex-col border-l border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-800">群組資訊</h3>
        <button type="button" aria-label="關閉" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {admin && (
          <form
            className="flex gap-2"
            onSubmit={(e) => { e.preventDefault(); const v = name.trim(); if (v) onRename(v); }}
          >
            <input
              aria-label="群組名稱" value={name} onChange={(e) => setName(e.target.value)}
              className="input flex-1"
            />
            <button type="submit" className="text-sm text-indigo-600">改名</button>
          </form>
        )}

        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">成員（{conversation.members.length}）</p>
          <ul className="space-y-1">
            {conversation.members.map((m) => {
              const mAdmin = conversation.roles[m.id] === 'admin';
              return (
                <li key={m.id} className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50">
                  <span className="flex-1 truncate text-sm text-slate-700">
                    {m.display_name}
                    {mAdmin && <span className="ml-1 rounded bg-indigo-100 px-1 text-xs text-indigo-600">管理員</span>}
                  </span>
                  {admin && m.id !== currentUserId && (
                    <>
                      <button
                        type="button"
                        onClick={() => onSetRole(m.id, mAdmin ? 'member' : 'admin')}
                        className="text-xs text-slate-500 hover:text-indigo-600"
                      >
                        {mAdmin ? '取消管理員' : '設為管理員'}
                      </button>
                      <button
                        type="button"
                        aria-label={`移除 ${m.display_name}`}
                        onClick={() => onRemoveMember(m.id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        移除
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {admin && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-xs font-medium text-slate-400">加入成員</p>
            {addableFriends.length > 0 && (
              <select
                aria-label="從好友加入"
                className="input w-full"
                value=""
                onChange={(e) => { if (e.target.value) onAddMember({ userId: e.target.value }); }}
              >
                <option value="">從好友選擇…</option>
                {addableFriends.map((c) => (
                  <option key={c.user_id} value={c.user_id}>{c.display_name}</option>
                ))}
              </select>
            )}
            <form
              className="flex gap-2"
              onSubmit={(e) => { e.preventDefault(); const v = email.trim(); if (v) { onAddMember({ email: v }); setEmail(''); } }}
            >
              <input
                aria-label="以 email 加入" type="email" placeholder="email 加非好友"
                value={email} onChange={(e) => setEmail(e.target.value)} className="input flex-1"
              />
              <button type="submit" className="text-sm text-indigo-600">加入</button>
            </form>
          </div>
        )}
      </div>

      <footer className="border-t border-slate-200 p-4">
        <button
          type="button"
          onClick={onLeave}
          className="w-full rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-100"
        >
          退出群組
        </button>
      </footer>
    </aside>
  );
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/GroupInfoPanel.test.tsx`
Expected: 2 passed。

- [ ] **Step 5: Thread header 加群組資訊鈕**

`frontend/chat/src/components/Thread.tsx`：`ThreadProps` 加 `onShowGroupInfo?: () => void;`；解構參數加 `onShowGroupInfo,`。header 內（與既有 📞 / 標題並列）加：

```tsx
        {onShowGroupInfo && (
          <button
            type="button"
            aria-label="群組資訊"
            onClick={onShowGroupInfo}
            className="rounded-lg px-3 py-1 text-lg hover:bg-slate-100"
          >
            ⓘ
          </button>
        )}
```

（若 header 目前是 `flex items-center justify-between` 含標題與 call 鈕，把這顆放在右側按鈕群組內。）

- [ ] **Step 6: ChatApp 掛 panel 與接 ApiClient**

`frontend/chat/src/ChatApp.tsx`：
- import 加 `import { GroupInfoPanel } from './components/GroupInfoPanel';` 與 `useState`（若未引入）。
- 加狀態：`const [showInfo, setShowInfo] = useState(false);`
- 加群組操作 handler（放在其他 useCallback 附近）：

```typescript
  const runGroupOp = useCallback(
    async (op: () => Promise<unknown>) => {
      try {
        await op();
        await loadConversations();
      } catch (err) {
        if (err instanceof UnauthorizedError) { onLogout(); return; }
        if (err instanceof ApiError) alert(err.message);
      }
    },
    [loadConversations, onLogout],
  );
```

- `Thread` 加 prop（在 group 時提供）：`onShowGroupInfo={isGroup ? () => setShowInfo(true) : undefined}`。
- 在最外層 `<div className="flex h-screen">…</div>` 內、`</div>` 前掛 panel：

```tsx
      {showInfo && isGroup && activeConv && (
        <GroupInfoPanel
          conversation={activeConv}
          currentUserId={currentUser.id}
          contacts={contacts}
          onAddMember={(opts) => runGroupOp(() => api.addMember(activeConv.id, opts))}
          onRemoveMember={(uid) => runGroupOp(() => api.removeMember(activeConv.id, uid))}
          onSetRole={(uid, role) => runGroupOp(() => api.setMemberRole(activeConv.id, uid, role))}
          onRename={(name) => runGroupOp(() => api.renameGroup(activeConv.id, name))}
          onLeave={() => runGroupOp(async () => { await api.leaveGroup(activeConv.id); setShowInfo(false); })}
          onClose={() => setShowInfo(false)}
        />
      )}
```

- [ ] **Step 7: 跑 chat 測試與 typecheck（含 shell）**

Run: `cd frontend/chat && npx vitest run && npm run typecheck`，再 `cd frontend/shell && npm run typecheck`
Expected: 全綠、兩個 tsc 乾淨。

- [ ] **Step 8: 手動 E2E（兩/三帳號，無法自動化，留給人工）**

依 CLAUDE.md 啟動整套。Alice 建群（Bob、Carol）→ 開群組 ⓘ → 改名、用 email 加 Dave（非好友）、把 Bob 設管理員、移除 Carol → 各端即時看到系統訊息與成員列更新；Carol 端對話消失。Bob（管理員）退出；Alice 為最後 admin 嘗試退出被擋，指派他人後退出。截圖 `group-mgmt-01..0N`。

- [ ] **Step 9: 更新文件**

`progress.md`：加「群組管理（成員/角色/改名）」已完成段落，註明 WS 系統訊息 + 不變式 + E2E 手動。
`docs/superpowers/specs/2026-06-19-group-chat-design.md`：把第 23–26 行的四個 `❌` 改為 `✅ ~~…~~ —— 已於 2026-06-21 實作，見 [群組管理設計](2026-06-21-group-management-design.md)。`

- [ ] **Step 10: Commit**

```bash
git add frontend/chat/src/components/GroupInfoPanel.tsx frontend/chat/src/components/GroupInfoPanel.test.tsx \
  frontend/chat/src/components/Thread.tsx frontend/chat/src/ChatApp.tsx \
  progress.md docs/superpowers/specs/2026-06-19-group-chat-design.md
git commit -m "[group-mgmt][feat][chat] GroupInfoPanel + ChatApp 接線 + 更新文件

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage（對照 spec 七節）：**
- §3 資料模型（role / kind + 回填 + 系統訊息文案）→ Task 1（model/migration/schema）。✅
- §4 REST API/權限（加/移/退/改名/角色 + 不變式 + direct 擋 + 權限）→ Task 2（加/移）、Task 3（退/改名/角色 + 不變式）。✅
- §5 WS 通知 + 系統訊息廣播（message system + conversation_updated/removed + 對象順序）→ Task 2 helper + Task 3 復用。✅
- §6 前端（contracts/ApiClient/store/groupPermissions/GroupInfoPanel/系統訊息渲染/ChatApp 接線）→ Task 4/5/6/7。✅
- §7 測試（遷移回填、權限矩陣、加非好友、不變式、刪空群、WS 廣播；前端 helper/store/panel/Thread）→ 各 task 測試。✅

**Placeholder scan：** 無 TBD/TODO；每個程式步驟附完整程式碼與確切指令。✅

**Type consistency：**
- 角色字面值 `'admin'|'member'`、kind `'user'|'system'` 跨 contracts / schemas / 服務一致。
- `ConversationOut.roles: dict[uuid,str]` ↔ 前端 `Conversation.roles: Record<string,'admin'|'member'>`（model_dump(mode='json') key 轉字串）。✅
- 服務函式 `get_role_map`/`get_member`/`is_group_admin`/`create_system_message`/`would_leave_groupless_of_admin` 在 Task 2 定義、Task 3 復用，簽章一致。
- router 廣播 helper `_system_message_payload`/`_push_system_and_updated`/`_push_removed`/`_require_group_admin` 在 Task 2 定義、Task 3 復用。
- `Message.kind?` 設為**選用**以避免既有前端 Message fixture/optimistic 全面破壞；後端一律帶 kind，渲染以 `=== 'system'` 判定，undefined 視同 user。✅

**已知取捨**：`remove_member` 的 admin 不變式不可能觸發（操作者本身 admin 未被移除），保留檢查以滿足規格字面，行為無害。已於 Task 2 註明。

無缺口。
