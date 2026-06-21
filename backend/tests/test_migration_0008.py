import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import Conversation, ConversationMember, Message, User


@pytest.mark.asyncio
async def test_reply_forward_columns_model(session_factory):
    """Test that the model columns exist and can be written/read."""
    async with session_factory() as s:
        u1 = User(email="user1@x.com", display_name="User 1", password_hash="h")
        u2 = User(email="user2@x.com", display_name="User 2", password_hash="h")
        s.add_all([u1, u2])
        await s.flush()
        conv = Conversation(type="direct", direct_key=f"{u1.id}:{u2.id}")
        s.add(conv)
        await s.flush()
        s.add_all([
            ConversationMember(conversation_id=conv.id, user_id=u1.id),
            ConversationMember(conversation_id=conv.id, user_id=u2.id),
        ])
        # Create a message to reply to
        original_msg = Message(
            conversation_id=conv.id, sender_id=u1.id, content="original"
        )
        s.add(original_msg)
        await s.flush()

        # Create a reply message
        reply_msg = Message(
            conversation_id=conv.id,
            sender_id=u2.id,
            content="reply",
            reply_to_message_id=original_msg.id,
            forwarded_from_user_id=None,
        )
        s.add(reply_msg)
        await s.flush()

        # Create a forwarded message
        forward_msg = Message(
            conversation_id=conv.id,
            sender_id=u1.id,
            content="forwarded",
            reply_to_message_id=None,
            forwarded_from_user_id=u2.id,
        )
        s.add(forward_msg)
        await s.commit()

        # Verify the columns were written and can be read
        got_reply = await s.get(Message, reply_msg.id)
        assert got_reply is not None
        assert got_reply.reply_to_message_id == original_msg.id
        assert got_reply.forwarded_from_user_id is None

        got_forward = await s.get(Message, forward_msg.id)
        assert got_forward is not None
        assert got_forward.reply_to_message_id is None
        assert got_forward.forwarded_from_user_id == u2.id


# Separate sync test function (not under pytestmark)
BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0008_creates_columns(tmp_path):
    """Smoke test: alembic upgrade head creates reply_to_message_id and forwarded_from_user_id columns."""
    db = tmp_path / "mig.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db)

    # Get columns info from messages table
    columns = {r[1]: (r[2], r[3], r[5]) for r in con.execute("PRAGMA table_info(messages)")}
    con.close()

    # Assert both columns exist
    assert "reply_to_message_id" in columns, f"reply_to_message_id not found in columns: {columns.keys()}"
    assert "forwarded_from_user_id" in columns, f"forwarded_from_user_id not found in columns: {columns.keys()}"
