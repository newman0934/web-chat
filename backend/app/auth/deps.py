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


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """需要登入的 REST 端點掛這個依賴；任一步失敗都拋 401。"""
    if not token:
        raise _credentials_exc
    user_id = decode_access_token(token)  # 驗簽 + 過期檢查，回 sub
    if user_id is None:
        raise _credentials_exc
    try:
        uid = uuid.UUID(user_id)  # sub 應為合法 UUID 字串
    except ValueError:
        raise _credentials_exc
    user = await db.get(User, uid)
    if user is None:  # token 合法但使用者已被刪
        raise _credentials_exc
    return user
