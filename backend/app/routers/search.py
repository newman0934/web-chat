"""全域訊息搜尋端點。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import User
from app.schemas import SearchResponseOut
from app.services.search import search_messages

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/messages", response_model=SearchResponseOut)
async def search_messages_endpoint(
    q: str = Query(min_length=1, max_length=100),
    before: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # strip 後仍可能為空(全空白)→ 422,不執行搜尋。
    term = q.strip()
    if not term:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="搜尋關鍵字不可為空",
        )
    return await search_messages(db, current_user.id, term, before, limit)
