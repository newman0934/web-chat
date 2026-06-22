"""站內通知測試。

Task 1：Notification model 落庫 roundtrip（schema 由 conftest 的 create_all 建立）。
後續 task 會在此檔補 service / WS 觸發 / REST 的測試。
"""

import uuid

import pytest

from app.models.notification import Notification


@pytest.mark.asyncio
async def test_notification_model_roundtrip(session_factory):
    """可建立並讀回一筆 Notification，預設未讀（read_at 為 None）、有 created_at。"""
    async with session_factory() as db:
        n = Notification(
            user_id=uuid.uuid4(),
            type="reaction",
            actor_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            emoji="👍",
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)

    assert n.id is not None
    assert n.type == "reaction"
    assert n.emoji == "👍"
    assert n.read_at is None
    assert n.created_at is not None
