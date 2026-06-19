"""使用者資訊端點。"""

from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.models import User
from app.schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """回傳目前登入者；shell 用此驗證 token 是否仍有效並取得 currentUser。"""
    return current_user
