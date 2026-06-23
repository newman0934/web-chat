"""FastAPI 認證依賴：從 Bearer token 解出目前登入的 User。"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.db import get_db
from app.models import User

# auto_error=False：缺 token 時不自動報錯，改由下方統一拋 401（訊息一致）。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# 各種驗證失敗一律回同一個 401，避免洩漏「token 無效」與「使用者不存在」的差異。
_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="無效或過期的憑證",
    headers={"WWW-Authenticate": "Bearer"},
)


async def resolve_user_from_token(db: AsyncSession, token: str | None) -> User | None:
    """從 raw token 解出 User;任一步失敗(缺 token / 驗簽過期 / sub 非 UUID / 使用者已刪)回 None。

    非拋例外版本,供 WebSocket、附件下載等需自行決定回應方式(關閉連線 / 404)的端點共用;
    get_current_user(REST 依賴)則在 None 時統一拋 401。
    """
    if not token:
        return None
    sub = decode_access_token(token)  # 驗簽 + 過期檢查，回 sub
    if sub is None:
        return None
    try:
        uid = uuid.UUID(sub)  # sub 應為合法 UUID 字串
    except ValueError:
        return None
    return await db.get(User, uid)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """需要登入的 REST 端點掛這個依賴；任一步失敗都拋 401。"""
    user = await resolve_user_from_token(db, token)
    if user is None:
        raise _credentials_exc
    return user
