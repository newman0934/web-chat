"""Pydantic schema：定義 REST API 的請求 / 回應外型（與 ORM model 分離）。

設 `from_attributes=True` 的 Out 類別可直接由 ORM 物件序列化（model_validate）。
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


def _utc_iso(dt: datetime | None) -> str | None:
    """把 datetime 序列化成 tz-aware UTC ISO 字串。

    SQLite（測試/開發）對 DateTime(timezone=True) 欄位回傳 naive datetime，
    Pydantic 預設會序列化成「無時區」ISO，前端 new Date() 會誤判為本地時間。
    這裡一律把 naive 視為 UTC（後端寫入的就是 UTC）並補上時區,確保前端正確。
    Postgres 回 tz-aware 則原樣輸出。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ---- 認證 / 使用者 ----
class RegisterRequest(BaseModel):
    email: EmailStr  # EmailStr 會驗證格式
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=128)  # 最少 6 碼


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str


# ---- contacts ----
class AddContactRequest(BaseModel):
    email: EmailStr


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: EmailStr
    display_name: str
    conversation_id: uuid.UUID
    online: bool = False
    last_seen_at: datetime | None = None  # 在線時通常為 null（前端只在離線顯示）

    @field_serializer("last_seen_at")
    def _ser_last_seen(self, dt: datetime | None) -> str | None:
        return _utc_iso(dt)


# ---- attachments ----
class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_name: str
    content_type: str
    size: int
    is_image: bool


# ---- 對話 / 訊息 ----
class ReactionGroupOut(BaseModel):
    emoji: str
    count: int
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class ReplyPreviewOut(BaseModel):
    """被引用原訊息的精簡預覽，嵌在回覆訊息的 reply_to 欄位。"""
    id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    deleted: bool
    has_attachment: bool


class ForwardedFromOut(BaseModel):
    """轉發訊息的原作者資訊，嵌在轉發訊息的 forwarded_from 欄位。"""
    id: uuid.UUID
    display_name: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    created_at: datetime
    read_count: int = 0  # 讀過此則的人數（排除寄件人）
    attachment: AttachmentOut | None = None
    edited_at: datetime | None = None
    deleted: bool = False
    deleted_at: datetime | None = None
    reactions: list[ReactionGroupOut] = Field(default_factory=list)
    kind: str = "user"
    reply_to: ReplyPreviewOut | None = None
    forwarded_from: ForwardedFromOut | None = None

    @field_serializer("created_at", "edited_at", "deleted_at")
    def _ser_dt(self, dt: datetime | None) -> str | None:
        return _utc_iso(dt)


class MessageVersionOut(BaseModel):
    content: str
    created_at: datetime

    @field_serializer("created_at")
    def _ser_dt(self, dt: datetime) -> str | None:
        return _utc_iso(dt)


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_user_ids: list[uuid.UUID] = Field(default_factory=list)


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID | None = None
    email: EmailStr | None = None


class GroupRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class RoleUpdateRequest(BaseModel):
    role: Literal["admin", "member"]


class ConversationOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str | None = None
    other_user: UserOut | None = None  # direct 才有
    members: list[UserOut] = Field(default_factory=list)
    last_message: MessageOut | None = None
    unread_count: int = 0
    roles: dict[uuid.UUID, str] = Field(default_factory=dict)


# ---- notifications ----
class NotificationActorOut(BaseModel):
    id: uuid.UUID
    display_name: str


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str  # reply|reaction|forward
    actor: NotificationActorOut
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    message_preview: str
    emoji: str | None = None
    read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut] = Field(default_factory=list)
    unread_count: int = 0


class MarkReadRequest(BaseModel):
    conversation_id: uuid.UUID
