# 圖片與檔案傳輸 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在現有聊天（1對1 + 群組）上新增最小可用的圖片/檔案附件：上傳到後端本機檔案系統，訊息引用，圖片內嵌、其他檔案下載。

**Architecture:** 附件採兩段式：先 `POST /uploads` 建孤兒 `Attachment`（檔存 `backend/uploads/`、DB 存中繼資料），再走現有 WS 送訊息路徑帶 `attachment_id` 綁定到 Message 並沿用群組廣播。下載走授權的 `GET /attachments/{id}`（接受 `?token=` 供 `<img>`）。

**Tech Stack:** FastAPI（UploadFile / FileResponse / python-multipart 已具備）、SQLAlchemy 2.0 async、Alembic、React 18 + Vite + Module Federation + zustand、pytest、Vitest。

**設計來源：** [docs/superpowers/specs/2026-06-20-file-attachments-design.md](../specs/2026-06-20-file-attachments-design.md)

## Global Constraints

- 後端測試以 venv 執行：`backend/.venv/Scripts/python.exe -m pytest`（PATH 的 `python` 是 Store stub，不可用）。
- 單檔上限 **10MB**（`MAX_UPLOAD_BYTES = 10 * 1024 * 1024`）；任意型別；`is_image = content_type.startswith("image/")`。
- `stored_name` 一律隨機 `uuid.uuid4().hex + 副檔名`，絕不用使用者檔名組磁碟路徑（防路徑穿越）。
- 下載端點需做對話成員權限檢查；接受 `Authorization: Bearer` 或 query `?token=`。
- UUID 用 SQLAlchemy 通用 `Uuid`；WS 端點維持用 `db_module.SessionLocal()`（勿改 get_db 依賴）；密碼勿引入 passlib；測試 DB 用檔案型 SQLite + `NullPool`。
- 後端測試走 SQLite，`Base.metadata.create_all`（conftest）已涵蓋新 model，不靠 migration。
- 前端 remote 改動後需 `npm run build` 才反映到 host。契約集中於 `frontend/contracts/index.ts`。
- Commit 訊息格式（CLAUDE.md）：`[feature][type][scope] description`，本功能 feature=`attachments`；結尾保留 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 每個 Task 結束都要相關測試 / `tsc --noEmit` 綠燈後再 commit。

---

### Task 1: Attachment 模型 + 儲存工具 + 設定

**Files:**
- Create: `backend/app/models/attachment.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/storage.py`
- Modify: `backend/app/config.py`（加 `upload_dir`）
- Modify: `backend/.gitignore` 或根 `.gitignore`（排除 `backend/uploads/`）
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces:
  - `Attachment(id, message_id: uuid|None, uploader_id, stored_name, original_name, content_type, size: int, is_image: bool, created_at)`，UNIQUE(message_id)
  - `app.storage.make_stored_name(original_name: str) -> str`
  - `app.storage.save_bytes(stored_name: str, data: bytes) -> None`
  - `app.storage.stored_path(stored_name: str) -> pathlib.Path`
  - `Settings.upload_dir: str`（預設 `backend/uploads` 絕對路徑）

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_storage.py`

```python
import re

from app import storage
from app.config import get_settings


def test_make_stored_name_is_random_with_ext():
    name = storage.make_stored_name("photo.PNG")
    assert re.fullmatch(r"[0-9a-f]{32}\.PNG", name)
    assert name != storage.make_stored_name("photo.PNG")


def test_save_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    stored = storage.make_stored_name("a.txt")
    storage.save_bytes(stored, b"hello")
    assert storage.stored_path(stored).read_bytes() == b"hello"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_storage.py -v`
Expected: FAIL（`ModuleNotFoundError: app.storage` 或 `upload_dir` 不存在）

- [ ] **Step 3: 改 `config.py`** — 在 `Settings` 內、`cors_origins` 之後加：

```python
    upload_dir: str = str(
        __import__("pathlib").Path(__file__).resolve().parents[1] / "uploads"
    )
```

- [ ] **Step 4: 建 `storage.py`**

```python
"""上傳檔案的本機儲存：隨機檔名、寫入 / 讀取，路徑來自 settings.upload_dir。"""

import uuid
from pathlib import Path

from app.config import get_settings


def _base_dir() -> Path:
    return Path(get_settings().upload_dir)


def make_stored_name(original_name: str) -> str:
    """隨機 uuid + 原副檔名，避免衝突與路徑穿越。"""
    ext = Path(original_name).suffix
    return f"{uuid.uuid4().hex}{ext}"


def save_bytes(stored_name: str, data: bytes) -> None:
    base = _base_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / stored_name).write_bytes(data)


def stored_path(stored_name: str) -> Path:
    return _base_dir() / stored_name
```

- [ ] **Step 5: 建 `models/attachment.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Attachment(Base):
    """訊息附件中繼資料。上傳時建立（message_id=NULL），送訊息時綁定。"""

    __tablename__ = "attachments"
    __table_args__ = (UniqueConstraint("message_id", name="uq_attachment_message"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_image: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 6: 改 `models/__init__.py`** — 加入並匯出 `Attachment`：

```python
from app.models.attachment import Attachment
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.message import Message
from app.models.message_read import MessageRead
from app.models.user import User

__all__ = [
    "User", "Contact", "Conversation", "ConversationMember",
    "Message", "MessageRead", "Attachment",
]
```

- [ ] **Step 7: 排除上傳目錄** — 在根 `.gitignore` 的 `# DB` 區塊附近加：

```
# Uploaded files
backend/uploads/
```

- [ ] **Step 8: 跑測試確認通過**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_storage.py -v`
Expected: PASS（2 passed）

- [ ] **Step 9: Commit**

```bash
git add backend/app/models backend/app/storage.py backend/app/config.py backend/tests/test_storage.py .gitignore
git commit -m "[attachments][feat][backend] Attachment 模型與本機儲存工具"
```

---

### Task 2: REST 上傳 / 下載端點 + MessageOut.attachment

**Files:**
- Modify: `backend/app/schemas.py`（`AttachmentOut`、`MessageOut.attachment`）
- Create: `backend/app/routers/uploads.py`（`/uploads` 與 `/attachments/{id}`）
- Modify: `backend/app/main.py`（掛載新 router）
- Modify: `backend/app/services/conversations.py`（`get_attachment_for_message`、`serialize_attachment` 輔助）
- Modify: `backend/app/routers/conversations.py`（`list_messages` 帶 attachment）
- Test: `backend/tests/test_uploads.py`

**Interfaces:**
- Consumes: Task 1 的 `Attachment`、`app.storage`。
- Produces:
  - `AttachmentOut { id, original_name, content_type, size, is_image }`
  - `MessageOut.attachment: AttachmentOut | None = None`
  - `POST /uploads -> AttachmentOut`（201）
  - `GET /attachments/{id}` → 檔案串流（200）/ 401 / 404
  - `app.services.conversations.get_attachment_for_message(db, message_id) -> Attachment | None`
  - `MAX_UPLOAD_BYTES = 10 * 1024 * 1024`（定義於 `uploads.py`）

- [ ] **Step 1: 寫失敗測試** — `backend/tests/test_uploads.py`

```python
import pytest

pytestmark = pytest.mark.asyncio


async def test_upload_returns_metadata(client, register_user, auth_headers):
    token = await register_user("up@example.com", "Up")
    resp = await client.post(
        "/uploads",
        files={"file": ("hello.txt", b"hello world", "text/plain")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["original_name"] == "hello.txt"
    assert data["is_image"] is False
    assert data["size"] == 11
    assert "id" in data


async def test_upload_detects_image(client, register_user, auth_headers):
    token = await register_user("img@example.com", "Img")
    resp = await client.post(
        "/uploads",
        files={"file": ("a.png", b"\x89PNG\r\n", "image/png")},
        headers=auth_headers(token),
    )
    assert resp.json()["is_image"] is True


async def test_upload_too_large_413(client, register_user, auth_headers):
    token = await register_user("big@example.com", "Big")
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        "/uploads",
        files={"file": ("big.bin", big, "application/octet-stream")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 413


async def test_download_orphan_only_uploader(client, register_user, auth_headers):
    owner = await register_user("own@example.com", "Own")
    other = await register_user("oth@example.com", "Oth")
    att = (await client.post(
        "/uploads",
        files={"file": ("f.txt", b"secret", "text/plain")},
        headers=auth_headers(owner),
    )).json()
    # 上傳者可下載
    ok = await client.get(f"/attachments/{att['id']}", headers=auth_headers(owner))
    assert ok.status_code == 200
    assert ok.content == b"secret"
    # 他人不可（孤兒附件）
    no = await client.get(f"/attachments/{att['id']}", headers=auth_headers(other))
    assert no.status_code == 404


async def test_download_accepts_query_token(client, register_user, auth_headers):
    owner = await register_user("q@example.com", "Q")
    att = (await client.post(
        "/uploads",
        files={"file": ("f.txt", b"hi", "text/plain")},
        headers=auth_headers(owner),
    )).json()
    resp = await client.get(f"/attachments/{att['id']}?token={owner}")
    assert resp.status_code == 200
    assert resp.content == b"hi"
```

> 註：`register_user` fixture 回傳的就是 token 字串（見現有 conftest），故 `?token={owner}` 直接用。

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_uploads.py -v`
Expected: FAIL（404，路由未存在）

- [ ] **Step 3: 改 `schemas.py`** — 在 `MessageOut` 之前加 `AttachmentOut`，並在 `MessageOut` 加欄位：

```python
class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    content_type: str
    size: int
    is_image: bool
```

在 `MessageOut` 內（`read_count` 之後）加：

```python
    attachment: AttachmentOut | None = None
```

- [ ] **Step 4: 加服務輔助** — `backend/app/services/conversations.py` 末端加：

```python
from app.models import Attachment  # 與檔案頂部既有 import 合併


async def get_attachment_for_message(
    db: AsyncSession, message_id: uuid.UUID
) -> Attachment | None:
    result = await db.execute(
        select(Attachment).where(Attachment.message_id == message_id)
    )
    return result.scalar_one_or_none()
```

> 將 `Attachment` 併入該檔頂部既有的 `from app.models import ...`，不要重複 import。

- [ ] **Step 5: 建 `routers/uploads.py`**

```python
"""檔案上傳與下載：存後端本機檔案系統，下載做對話成員權限檢查。"""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.security import decode_access_token
from app.db import get_db
from app.models import Attachment, Message, User
from app.schemas import AttachmentOut
from app.services.conversations import get_conversation_for_member
from app.storage import make_stored_name, save_bytes, stored_path

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/uploads", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空檔案")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="檔案過大（上限 10MB）")

    content_type = file.content_type or "application/octet-stream"
    original_name = file.filename or "file"
    stored = make_stored_name(original_name)
    save_bytes(stored, data)

    att = Attachment(
        uploader_id=current_user.id,
        message_id=None,
        stored_name=stored,
        original_name=original_name,
        content_type=content_type,
        size=len(data),
        is_image=content_type.startswith("image/"),
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    return att


async def _resolve_user(
    db: AsyncSession, token: str | None, authorization: str | None
) -> User | None:
    raw = token
    if raw is None and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    if not raw:
        return None
    sub = decode_access_token(raw)
    if sub is None:
        return None
    try:
        uid = uuid.UUID(sub)
    except ValueError:
        return None
    return await db.get(User, uid)


@router.get("/attachments/{attachment_id}")
async def download(
    attachment_id: uuid.UUID,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_user(db, token, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="未授權")

    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="查無附件")

    # 權限：孤兒附件僅上傳者；已綁定附件須為該對話成員。
    if att.message_id is None:
        if att.uploader_id != user.id:
            raise HTTPException(status_code=404, detail="查無附件")
    else:
        msg = await db.get(Message, att.message_id)
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="查無附件")

    path = stored_path(att.stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="檔案不存在")

    if att.is_image:
        disposition = "inline"
    else:
        disposition = f'attachment; filename="{att.original_name}"'
    return FileResponse(
        path,
        media_type=att.content_type,
        headers={"Content-Disposition": disposition},
    )
```

- [ ] **Step 6: 掛載 router** — `backend/app/main.py`：import 並 `app.include_router(uploads.router)`：

```python
from app.routers import auth, contacts, conversations, uploads, users
# ...
app.include_router(uploads.router)
```

- [ ] **Step 7: `list_messages` 帶 attachment** — `backend/app/routers/conversations.py` 的 `list_messages` 內，建 `MessageOut` 時補 attachment（並 import 輔助）：

```python
from app.services.conversations import (
    get_attachment_for_message,
    get_conversation_for_member,
    read_count,
)
# ... 在組裝 MessageOut 的清單推導內：
    out = []
    for m in messages:
        att = await get_attachment_for_message(db, m.id)
        out.append(
            MessageOut(
                id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
                content=m.content, created_at=m.created_at,
                read_count=await read_count(db, m.id),
                attachment=AttachmentOut.model_validate(att) if att else None,
            )
        )
    return out
```

並把 `AttachmentOut` 加入該檔的 `from app.schemas import ...`。

- [ ] **Step 8: 跑測試確認通過 + 全後端回歸**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS（新 test_uploads 全過；既有測試不受影響，MessageOut.attachment 預設 None）

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas.py backend/app/routers backend/app/services/conversations.py backend/tests/test_uploads.py
git commit -m "[attachments][feat][backend] /uploads 與 /attachments 端點 + MessageOut.attachment"
```

---

### Task 3: WebSocket 送附件訊息

**Files:**
- Modify: `backend/app/ws/router.py`
- Test: `backend/tests/test_ws_attachments.py`

**Interfaces:**
- Consumes: Task 1/2（`Attachment`、`get_attachment_for_message`、`AttachmentOut`）。
- Produces（WS 行為）：
  - 送訊息可帶 `attachment_id`；`content` 可空（有附件時）。
  - ack / 廣播的 `message` 物件新增 `attachment` 欄位（無則 `null`）。

- [ ] **Step 1: 改 `_serialize_message`** — `backend/app/ws/router.py`，讓序列化帶 attachment：

```python
from app.schemas import AttachmentOut  # 併入既有 import


def _serialize_message(msg: Message, read_count: int = 0, attachment=None) -> dict:
    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": msg.content,
        "created_at": msg.created_at.astimezone(timezone.utc).isoformat(),
        "read_count": read_count,
        "attachment": (
            AttachmentOut.model_validate(attachment).model_dump(mode="json")
            if attachment
            else None
        ),
    }
```

- [ ] **Step 2: 改 `_handle_send`** — 支援 attachment_id、放寬空 content：

```python
from app.models import Attachment, Message, User  # 併入既有 import


async def _handle_send(websocket, user, data):
    conv_id_raw = data.get("conversation_id")
    content = (data.get("content") or "").strip()
    temp_id = data.get("temp_id")
    attachment_id_raw = data.get("attachment_id")

    if not conv_id_raw or (not content and not attachment_id_raw):
        await websocket.send_json(
            {"type": "error", "reason": "invalid_payload", "temp_id": temp_id}
        )
        return
    try:
        conv_id = uuid.UUID(str(conv_id_raw))
    except ValueError:
        await websocket.send_json(
            {"type": "error", "reason": "invalid_conversation", "temp_id": temp_id}
        )
        return

    async with db_module.SessionLocal() as db:
        conv = await get_conversation_for_member(db, conv_id, user.id)
        if conv is None:
            await websocket.send_json(
                {"type": "error", "reason": "forbidden", "temp_id": temp_id}
            )
            return

        attachment = None
        if attachment_id_raw:
            try:
                att_id = uuid.UUID(str(attachment_id_raw))
            except ValueError:
                await websocket.send_json(
                    {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
                )
                return
            attachment = await db.get(Attachment, att_id)
            if (
                attachment is None
                or attachment.uploader_id != user.id
                or attachment.message_id is not None
            ):
                await websocket.send_json(
                    {"type": "error", "reason": "invalid_attachment", "temp_id": temp_id}
                )
                return

        message = Message(conversation_id=conv_id, sender_id=user.id, content=content)
        db.add(message)
        try:
            await db.commit()
            await db.refresh(message)
            if attachment is not None:
                attachment.message_id = message.id
                await db.commit()
                await db.refresh(attachment)
        except Exception:
            await db.rollback()
            await websocket.send_json(
                {"type": "error", "reason": "db_error", "temp_id": temp_id}
            )
            return

        payload = _serialize_message(message, attachment=attachment)
        recipients = await get_other_member_ids(db, conv_id, user.id)

    await websocket.send_json({"type": "ack", "temp_id": temp_id, "message": payload})
    for rid in recipients:
        if manager.is_online(rid):
            await manager.send_to_user(rid, {"type": "message", "message": payload})
```

- [ ] **Step 3: 寫測試** — `backend/tests/test_ws_attachments.py`

```python
import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _direct(client, register_user, auth_headers):
    alice = await register_user("aa@example.com", "Alice")
    bob = await register_user("ab@example.com", "Bob")
    await client.post("/contacts", json={"email": "ab@example.com"}, headers=auth_headers(alice))
    conv = (await client.get("/conversations", headers=auth_headers(alice))).json()[0]
    return alice, bob, conv["id"]


async def test_ws_message_with_attachment(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    att = (await client.post(
        "/uploads",
        files={"file": ("p.png", b"\x89PNG", "image/png")},
        headers=auth_headers(alice),
    )).json()

    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "", "attachment_id": att["id"], "temp_id": "t1",
            })
            ack = wa.receive_json()
            assert ack["type"] == "ack"
            assert ack["message"]["attachment"]["id"] == att["id"]
            assert ack["message"]["attachment"]["is_image"] is True

    # 歷史也帶 attachment
    history = await client.get(f"/conversations/{conv_id}/messages", headers=auth_headers(bob))
    assert history.json()[0]["attachment"]["original_name"] == "p.png"


async def test_ws_rejects_used_or_foreign_attachment(client, register_user, auth_headers):
    alice, bob, conv_id = await _direct(client, register_user, auth_headers)
    # Bob 的附件，Alice 不能用
    bob_att = (await client.post(
        "/uploads",
        files={"file": ("x.txt", b"x", "text/plain")},
        headers=auth_headers(bob),
    )).json()
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({
                "type": "message", "conversation_id": conv_id,
                "content": "hi", "attachment_id": bob_att["id"], "temp_id": "t",
            })
            assert wa.receive_json()["reason"] == "invalid_attachment"


async def test_ws_empty_content_no_attachment_invalid(client, register_user, auth_headers):
    alice, _bob, conv_id = await _direct(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as wa:
            wa.send_json({"type": "message", "conversation_id": conv_id, "content": "", "temp_id": "t"})
            assert wa.receive_json()["reason"] == "invalid_payload"
```

- [ ] **Step 4: 跑測試 + 全後端回歸**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS（既有 WS 測試仍綠；ack/push 的 message 多了 `attachment` 欄位，既有斷言不檢查它故不受影響）

- [ ] **Step 5: Commit**

```bash
git add backend/app/ws/router.py backend/tests/test_ws_attachments.py
git commit -m "[attachments][feat][ws] 送訊息支援 attachment_id 與序列化附件"
```

---

### Task 4: 前端契約 + api.uploadFile + messageStore

**Files:**
- Modify: `frontend/contracts/index.ts`
- Modify: `frontend/chat/src/api.ts`
- Modify: `frontend/chat/src/messageStore.ts`
- Modify: `frontend/chat/src/messageStore.test.ts`、`frontend/chat/src/store.test.ts`（測試 helper 補 attachment）
- Test: `frontend/chat/src/messageStore.test.ts`（新增一例）

**Interfaces:**
- Produces:
  - 契約 `Attachment { id, original_name, content_type, size, is_image }`；`Message.attachment: Attachment | null`；`ClientWsMessage` 的 `message` 變體加選填 `attachment_id?: string`；`AttachmentOut = Attachment`。
  - `ApiClient.uploadFile(file: File): Promise<Attachment>`
  - `makeOptimistic(conversationId, senderId, content, tempId, attachment?: Attachment | null): ChatMessage`（attachment 預設 null）

- [ ] **Step 1: 改契約** — `frontend/contracts/index.ts`

```typescript
export interface Attachment {
  id: string;
  original_name: string;
  content_type: string;
  size: number;
  is_image: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  created_at: string;
  read_count: number;
  attachment: Attachment | null;
}

export type AttachmentOut = Attachment;
```

並把 `ClientWsMessage` 的 message 變體改為：

```typescript
  | { type: 'message'; conversation_id: string; content: string; temp_id: string; attachment_id?: string }
```

- [ ] **Step 2: 更新測試 helper（先讓既有測試相容新型別）** — 在 `messageStore.test.ts` 與 `store.test.ts` 的 `realMessage`/`realMsg` 回傳物件加 `attachment: null`。新增一例到 `messageStore.test.ts`：

```typescript
it('makeOptimistic 可帶附件', () => {
  const att = { id: 'a1', original_name: 'p.png', content_type: 'image/png', size: 3, is_image: true };
  const m = makeOptimistic('c1', 'me', '', 't1', att);
  expect(m.attachment).toEqual(att);
  expect(m.status).toBe('sending');
});
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts`
Expected: FAIL（`makeOptimistic` 尚不接受第 5 參數 / 型別錯）

- [ ] **Step 4: 改 `messageStore.ts`** — `makeOptimistic` 加附件參數、回傳帶 attachment；其餘函式因 `ChatMessage extends Message` 自動相容：

```typescript
import type { Attachment, Message } from '../../contracts';

export function makeOptimistic(
  conversationId: string,
  senderId: string,
  content: string,
  tempId: string,
  attachment: Attachment | null = null,
): ChatMessage {
  return {
    id: tempId,
    conversation_id: conversationId,
    sender_id: senderId,
    content,
    created_at: new Date().toISOString(),
    read_count: 0,
    attachment,
    temp_id: tempId,
    status: 'sending',
  };
}
```

- [ ] **Step 5: 改 `api.ts`** — 新增 `uploadFile`：

```typescript
import type { Attachment, Contact, Conversation, GroupCreateRequest, Message } from '../../contracts';

  /** 上傳單一檔案，回附件中繼資料。不手動設 Content-Type，讓瀏覽器帶 multipart boundary。 */
  async uploadFile(file: File): Promise<Attachment> {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch(`${this.baseUrl}/uploads`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}` },
      body: form,
    });
    if (resp.status === 401) throw new UnauthorizedError();
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new ApiError(data.detail ?? `上傳失敗 (${resp.status})`, resp.status);
    }
    return (await resp.json()) as Attachment;
  }
```

- [ ] **Step 6: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/messageStore.test.ts src/store.test.ts`
Expected: PASS

> 注意：此 Task 後 `ChatApp.tsx`/`Thread.tsx` 仍未用到附件，但因 `Message` 新增的 `attachment` 來自伺服器資料、非元件建構，故 `tsc` 不應因此爆。如有殘留型別錯誤（例如某處建構 Message 字面值），於 Task 6 整合時一併解決；本 Task 僅需上述兩個測試檔綠燈。

- [ ] **Step 7: Commit**

```bash
git add frontend/contracts/index.ts frontend/chat/src/api.ts frontend/chat/src/messageStore.ts frontend/chat/src/messageStore.test.ts frontend/chat/src/store.test.ts
git commit -m "[attachments][feat][contracts] 契約 attachment + api.uploadFile + makeOptimistic 附件"
```

---

### Task 5: Thread 訊息泡泡渲染附件

**Files:**
- Modify: `frontend/chat/src/components/Thread.tsx`
- Modify: `frontend/chat/src/components/Thread.test.tsx`

**Interfaces:**
- Consumes: Task 4 的 `Message.attachment`。
- Produces: `Thread` 新增 prop `attachmentUrl: (id: string) => string`；`MessageBubble` 依 `message.attachment` 渲染圖片 `<img>` 或下載連結。

- [ ] **Step 1: 更新/新增測試** — `frontend/chat/src/components/Thread.test.tsx`

`msg(...)` helper 補 `attachment: null`；所有既有 `<Thread .../>` render 補 `attachmentUrl={(id) => 'http://api/attachments/' + id}`。新增：

```typescript
it('圖片附件渲染 img、檔案附件渲染下載連結', () => {
  render(
    <Thread
      title="Bob" isGroup={false} memberNames={{}}
      attachmentUrl={(id) => `http://api/attachments/${id}`}
      messages={[
        msg({ id: 'm1', attachment: { id: 'img1', original_name: 'p.png', content_type: 'image/png', size: 3, is_image: true } }),
        msg({ id: 'm2', attachment: { id: 'doc1', original_name: 'r.pdf', content_type: 'application/pdf', size: 9, is_image: false } }),
      ]}
      currentUserId="me" canLoadMore={false}
      onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
    />,
  );
  const img = screen.getByRole('img');
  expect(img).toHaveAttribute('src', 'http://api/attachments/img1');
  const link = screen.getByRole('link', { name: /r\.pdf/ });
  expect(link).toHaveAttribute('href', 'http://api/attachments/doc1');
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: FAIL（Thread 不接受 attachmentUrl；無 img/連結）

- [ ] **Step 3: 改 `Thread.tsx`** — `ThreadProps` 加 `attachmentUrl: (id: string) => string`，傳給 `MessageBubble`；`MessageBubble` 在 content 之前渲染附件：

```tsx
// ThreadProps 加：attachmentUrl: (id: string) => string;
// 把 attachmentUrl 解構並傳入每個 <MessageBubble ... attachmentUrl={attachmentUrl} />

// MessageBubble 參數加 attachmentUrl，content <p> 之前插入：
{message.attachment && (
  message.attachment.is_image ? (
    <a href={attachmentUrl(message.attachment.id)} target="_blank" rel="noreferrer">
      <img
        src={attachmentUrl(message.attachment.id)}
        alt={message.attachment.original_name}
        className="mb-1 max-h-60 max-w-full rounded-lg"
      />
    </a>
  ) : (
    <a
      href={attachmentUrl(message.attachment.id)}
      target="_blank"
      rel="noreferrer"
      className="mb-1 flex items-center gap-2 rounded-lg bg-black/10 px-3 py-2 text-sm underline"
    >
      📎 {message.attachment.original_name}
      <span className="opacity-70">({message.attachment.size} bytes)</span>
    </a>
  )
)}
```

`MessageBubble` 的型別簽名加 `attachmentUrl: (id: string) => string`。

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/Thread.test.tsx`
Expected: PASS

> 此 Task 後 `ChatApp.tsx` 尚未傳 `attachmentUrl`，故全專案 `tsc` 會報錯（預期）；Task 6 整合時補齊。本 Task 僅需 Thread 測試綠燈，**不要**跑全 `tsc`。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/components/Thread.tsx frontend/chat/src/components/Thread.test.tsx
git commit -m "[attachments][feat][chat] 訊息泡泡渲染圖片/檔案附件"
```

---

### Task 6: Composer 上傳 + ChatApp 整合

**Files:**
- Modify: `frontend/chat/src/components/Thread.tsx`（composer 📎 + onSend 簽名）
- Modify: `frontend/chat/src/ChatApp.tsx`（onUpload、attachmentUrl、sendMessage 簽名）
- Test: 以 `tsc --noEmit` + 全 vitest 綠燈為準

**Interfaces:**
- Consumes: Task 4（`api.uploadFile`、`makeOptimistic` 附件）、Task 5（`attachmentUrl`、附件渲染）。
- Produces: `Thread` prop `onUpload: (file: File) => Promise<Attachment | null>`；`onSend: (content: string, attachmentId?: string) => void`。

- [ ] **Step 1: 改 `Thread.tsx` composer** — 加附件狀態與檔案輸入：

```tsx
// ThreadProps：onSend 改為 (content: string, attachmentId?: string) => void；
//              新增 onUpload: (file: File) => Promise<Attachment | null>;
// 在元件內：
const [pending, setPending] = useState<Attachment | null>(null);
const [uploading, setUploading] = useState(false);
const fileRef = useRef<HTMLInputElement | null>(null);

const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const f = e.target.files?.[0];
  e.target.value = '';
  if (!f) return;
  setUploading(true);
  const att = await onUpload(f);
  setUploading(false);
  if (att) setPending(att);
};

const submit = (e: React.FormEvent) => {
  e.preventDefault();
  const content = draft.trim();
  if (!content && !pending) return;
  onSend(content, pending?.id);
  setDraft('');
  setPending(null);
};
```

composer JSX：在輸入框旁加 📎 按鈕觸發隱藏 `<input type="file">`；若 `pending` 顯示檔名 chip + 移除鈕；`uploading` 時送出鈕 disabled。`import type { Attachment } from '../../../contracts'`，並引入 `useRef`。

- [ ] **Step 2: 改 `ChatApp.tsx`** — 提供 attachmentUrl / onUpload，sendMessage 帶附件：

```tsx
const attachmentUrl = useCallback(
  (id: string) => `${apiBaseUrl}/attachments/${id}?token=${encodeURIComponent(token)}`,
  [apiBaseUrl, token],
);

const onUpload = useCallback(
  async (file: File) => {
    try {
      return await api.uploadFile(file);
    } catch (err) {
      if (err instanceof UnauthorizedError) onLogout();
      return null;
    }
  },
  [api, onLogout],
);

// sendMessage 改簽名：(content: string, attachmentId?: string)
const sendMessage = useCallback(
  (content: string, attachmentId?: string) => {
    const st = useChatStore.getState();
    const active = st.activeId;
    if (!active) return;
    const tempId = crypto.randomUUID();
    // 樂觀訊息：若有附件，用 pending 的中繼資料（由 store 取不到，故從 conversations? 不可）
    // 簡化：樂觀訊息先不帶附件預覽，待 ack 帶回正式 attachment 再顯示。
    st.appendOptimistic(active, makeOptimistic(active, currentUser.id, content, tempId));
    const ok = socketRef.current?.send({
      type: 'message', conversation_id: active, content, temp_id: tempId,
      attachment_id: attachmentId,
    });
    if (!ok) useChatStore.getState().failMessage(tempId);
  },
  [currentUser.id],
);
```

並把 `<Thread>` 補上 `attachmentUrl={attachmentUrl}` 與 `onUpload={onUpload}`，`onSend={sendMessage}`（簽名已相容）。

> 設計取捨：樂觀訊息送出當下不帶附件預覽，待 server `ack` 回傳正式 `message.attachment` 由 `reconcileAck` 換上後即顯示。這比把 pending attachment 從 Thread 傳回 ChatApp 再塞進樂觀訊息簡單，且 ack 幾乎即時。

- [ ] **Step 3: typecheck + 全 vitest（chat）+ shell typecheck**

Run:
```bash
cd frontend/chat && npx tsc --noEmit && npx vitest run
cd ../shell && npx tsc --noEmit
```
Expected: 全 PASS（chat tsc 乾淨、vitest 全綠；shell tsc 乾淨）

- [ ] **Step 4: Commit**

```bash
git add frontend/chat/src/components/Thread.tsx frontend/chat/src/ChatApp.tsx
git commit -m "[attachments][feat][chat] composer 上傳附件與 ChatApp 整合"
```

---

### Task 7: Alembic 遷移 + 端到端煙霧 + 文件

**Files:**
- Create: `backend/alembic/versions/0003_attachments.py`
- Modify: `docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md`、`progress.md`、`README.md`

**Interfaces:**
- Consumes: Task 1 的 `Attachment` schema。

- [ ] **Step 1: 寫遷移** — `backend/alembic/versions/0003_attachments.py`

```python
"""attachments table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("stored_name", sa.String(length=255), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("is_image", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_attachment_message"),
    )


def downgrade() -> None:
    op.drop_table("attachments")
```

- [ ] **Step 2: 驗證遷移（乾淨 DB）**

```bash
cd backend
export DATABASE_URL="sqlite+aiosqlite:///C:/Users/caesar/Desktop/project/chat-web/backend/_mig3.db"
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -c "import sqlite3; print('attachments' in [r[0] for r in sqlite3.connect('_mig3.db').execute(\"select name from sqlite_master where type='table'\")])"
rm backend/_mig3.db
```
Expected: 印出 `True`，指令 exit 0。

- [ ] **Step 3: 啟動整套 + 瀏覽器煙霧** — 依 CLAUDE.md 啟動（backend SQLite、auth/chat build+preview、shell dev）。重建 `backend/dev.db`（`alembic upgrade head`）。用瀏覽器：登入 → 開一個對話 → 點 📎 選一張圖片送出 → 確認對話內**內嵌顯示該圖**；再送一個非圖片檔 → 確認顯示**下載連結**可下載。截圖存 `docs/`。

- [ ] **Step 4: 更新文件** — MVP spec 把「圖片/檔案傳輸」標為已實作（連到本設計）；`progress.md` 補附件功能現況與 follow-up；`README.md` 補附件說明。

- [ ] **Step 5: 全測試總跑**

Run:
```bash
cd backend && .venv/Scripts/python.exe -m pytest -q
cd ../frontend/chat && npx vitest run && npx tsc --noEmit
cd ../shell && npx vitest run && npx tsc --noEmit
cd ../auth && npx vitest run && npx tsc --noEmit
```
Expected: 全 PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0003_attachments.py docs progress.md README.md
git commit -m "[attachments][feat][db] Alembic 0003 attachments 遷移、文件與煙霧驗證"
```

---

## Self-Review（計畫對照 spec）

- **Spec §3 資料模型（Attachment、兩段式）** → Task 1（model）+ Task 7（migration）。✅
- **Spec §4 REST（/uploads 413/400、/attachments 權限、token query）** → Task 2。✅
- **Spec §5 WS（attachment_id、放寬空 content、invalid_attachment、序列化帶 attachment）** → Task 3。✅
- **Spec §6 前端（契約、api.uploadFile、makeOptimistic、Thread 渲染、composer、ChatApp attachmentUrl）** → Task 4/5/6。✅
- **Spec §7 測試** → 各 Task 內 TDD；Task 7 端到端。✅
- **Spec §8 安全（隨機檔名、成員權限、大小上限、uploads gitignore）** → Task 1（gitignore/隨機名）、Task 2（權限/大小）。✅

型別一致性：`AttachmentOut`(後端) ↔ `Attachment`(前端) 五欄位一致；`MessageOut.attachment` / `Message.attachment` / WS `_serialize_message` 的 `attachment` 對齊；`uploadFile`/`/uploads`/`POST` 對齊；`attachment_id`(client WS) ↔ 後端 `_handle_send` 讀取對齊；`attachmentUrl`/`onUpload`/`onSend(content, attachmentId?)` 三者在 Task 5/6 定義與使用一致。無未定義引用。

> 耦合備註：Task 5 改 Thread props（加 `attachmentUrl`）會讓 ChatApp 的全 `tsc` 暫時失敗，至 Task 6 補齊；故 Task 5 只跑 Thread 測試、Task 6 才跑全 `tsc`（與群組功能前端流程相同模式）。
