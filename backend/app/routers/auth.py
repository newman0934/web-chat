"""註冊與登入：兩者成功都直接回傳 JWT，前端拿到即視為已登入。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password, verify_password
from app.db import get_db
from app.models import User
from app.ratelimit import login_limiter, register_limiter
from app.schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    """以來源 IP 當速率限制 key(直連取 client.host;正式環境若在反向代理後,
    應於代理層設好可信的 X-Forwarded-For 再據此取值)。"""
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    key = _client_key(request)
    # 該 IP 近期建帳號過多 → 擋下(防自動化大量註冊);每次嘗試都計入。
    if not register_limiter.allowed(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="註冊次數過多，請稍後再試",
        )
    register_limiter.record(key)
    # email 唯一，先檢查避免撞 DB unique 約束才報錯。
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="此 email 已被註冊"
        )
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),  # 只存 hash
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)  # 取回 DB 產生的 id
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    key = _client_key(request)
    # 該 IP 近期登入失敗過多 → 擋下(降低暴力破解速度);成功登入不計入。
    if not login_limiter.allowed(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登入嘗試次數過多，請稍後再試",
        )
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    # 帳號不存在與密碼錯誤回相同訊息，不洩漏「此 email 是否註冊過」。
    if user is None or not verify_password(payload.password, user.password_hash):
        login_limiter.record(key)  # 只記失敗
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="email 或密碼錯誤"
        )
    return TokenResponse(access_token=create_access_token(user.id))
