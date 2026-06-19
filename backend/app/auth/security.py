"""密碼雜湊與 JWT 簽發 / 驗證。

密碼刻意直接用 bcrypt 套件，不用 passlib（passlib 1.7.4 與 bcrypt 4.x 不相容）。
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

_settings = get_settings()

# bcrypt 僅取前 72 bytes；超過會在 4.x 直接報錯，故先截斷（與舊版 passlib 行為一致）。
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_to_bcrypt_bytes(password), password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """簽發 JWT，sub=user_id、exp=現在+設定的有效分鐘數。"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=_settings.jwt_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """回傳 user_id（sub），無效則回 None。"""
    try:
        payload = jwt.decode(
            token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm]
        )
    except JWTError:
        return None
    return payload.get("sub")
