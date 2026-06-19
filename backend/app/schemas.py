"""Pydantic schema：定義 REST API 的請求 / 回應外型（與 ORM model 分離）。

設 `from_attributes=True` 的 Out 類別可直接由 ORM 物件序列化（model_validate）。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- auth / user ----
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


# ---- conversations / messages ----
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    created_at: datetime
    read_at: datetime | None = None  # None 表示尚未被對方讀取


class ConversationOut(BaseModel):
    # 對話清單用：聚合對方資訊、最後一則訊息與未讀數（非單純 ORM 映射，由 router 組裝）。
    id: uuid.UUID
    other_user: UserOut
    last_message: MessageOut | None = None
    unread_count: int = 0
