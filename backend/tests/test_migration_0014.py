"""0014 遷移煙霧測試:attachments 移除 message_id 唯一約束、改普通索引。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0014_drops_unique_adds_index(tmp_path):
    db = tmp_path / "mig0014.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(db)
    indexes = con.execute("PRAGMA index_list(attachments)").fetchall()
    cols = {r[1] for r in con.execute("PRAGMA table_info(attachments)")}
    con.close()
    assert "position" in cols, f"position 欄未建立:{cols}"
    names = {r[1] for r in indexes}
    # 唯一約束的自動索引不應再存在;普通 message_id 索引應存在。
    assert "uq_attachment_message" not in names, f"唯一約束未移除:{names}"
    assert "ix_attachments_message_id" in names, f"索引未建立:{names}"
    # message_id 上不應再有唯一索引(排除主鍵 id 的 pk autoindex,origin=r[3]=='pk')。
    assert all(r[2] == 0 for r in indexes if r[3] != "pk"), f"仍有唯一索引:{indexes}"
