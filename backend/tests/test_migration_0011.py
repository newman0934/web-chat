"""0011 遷移煙霧測試:alembic upgrade head 後 message_reads 應有 user_id 索引。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0011_creates_user_id_index(tmp_path):
    db = tmp_path / "mig0011.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(db)
    index_names = {r[1] for r in con.execute("PRAGMA index_list(message_reads)")}
    con.close()
    assert "ix_message_reads_user_id" in index_names, f"索引未建立:{index_names}"
