"""回歸測試：0005 把既有 group creator 回填為 admin、其餘 member；0006 訊息 kind 回填 user。
實跑 alembic（升到 0004 → 塞舊資料 → 升到 head），不重寫搬移邏輯。
"""
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"alembic upgrade {revision} failed:\n{result.stderr}"


def test_migration_backfills_role_and_kind(tmp_path):
    db = tmp_path / "mig.db"
    _alembic(db, "0004")  # 舊 schema：conversation_members 無 role、messages 無 kind

    creator = uuid.uuid4().hex
    other = uuid.uuid4().hex
    conv = uuid.uuid4().hex
    raw = sqlite3.connect(db)
    raw.execute("INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
                (creator, "c@x.com", "C", "h"))
    raw.execute("INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
                (other, "o@x.com", "O", "h"))
    raw.execute("INSERT INTO conversations (id, type, name, creator_id) VALUES (?,?,?,?)",
                (conv, "group", "G", creator))
    raw.execute("INSERT INTO conversation_members (id, conversation_id, user_id) VALUES (?,?,?)",
                (uuid.uuid4().hex, conv, creator))
    raw.execute("INSERT INTO conversation_members (id, conversation_id, user_id) VALUES (?,?,?)",
                (uuid.uuid4().hex, conv, other))
    raw.execute("INSERT INTO messages (id, conversation_id, sender_id, content) VALUES (?,?,?,?)",
                (uuid.uuid4().hex, conv, creator, "hi"))
    raw.commit()
    raw.close()

    _alembic(db, "head")

    check = sqlite3.connect(db)
    roles = dict(check.execute(
        "SELECT user_id, role FROM conversation_members WHERE conversation_id=?", (conv,)
    ).fetchall())
    assert roles[creator] == "admin"
    assert roles[other] == "member"
    kinds = [r[0] for r in check.execute("SELECT kind FROM messages").fetchall()]
    assert kinds == ["user"]
    check.close()
