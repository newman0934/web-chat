"""線上狀態(presence)測試。

Task 1：User.last_seen_at 欄位(schema 由 conftest 的 create_all 建立)。
後續 task 會補 manager first/last、presence service、WS 廣播、/contacts 帶 presence。
"""

import uuid

import pytest

from app.models import User


@pytest.mark.asyncio
async def test_user_last_seen_defaults_null(session_factory):
    """User 預設 last_seen_at 為 None,可寫入時間。"""
    async with session_factory() as db:
        u = User(
            email=f"p-{uuid.uuid4().hex[:8]}@e2e.test",
            display_name="P",
            password_hash="x",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        assert u.last_seen_at is None
