import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import Conversation, ConversationMember, Message, MessageEdit, User


@pytest.mark.asyncio
async def test_message_edit_round_trips(session_factory):
    async with session_factory() as s:
        u = User(email="me@x.com", display_name="Me", password_hash="h")
        s.add(u)
        await s.flush()
        conv = Conversation(type="direct", direct_key=f"{u.id}:{u.id}")
        s.add(conv)
        await s.flush()
        s.add(ConversationMember(conversation_id=conv.id, user_id=u.id))
        msg = Message(conversation_id=conv.id, sender_id=u.id, content="v2")
        s.add(msg)
        await s.flush()
        from datetime import datetime, timezone
        edit = MessageEdit(
            message_id=msg.id, content="v1", created_at=datetime.now(timezone.utc)
        )
        s.add(edit)
        await s.commit()
        got = await s.get(MessageEdit, edit.id)
        assert got is not None
        assert got.content == "v1"
        assert got.message_id == msg.id


# 獨立的同步測試函式(不套用 module 級 pytestmark)
BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0007_creates_table(tmp_path):
    db = tmp_path / "mig.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "message_edits" in names
