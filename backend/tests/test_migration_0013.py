"""0013 遷移煙霧測試:alembic upgrade head 後 messages 應有 recalled_at 欄。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migration_0013_adds_recalled_at(tmp_path):
    db = tmp_path / "mig0013.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
    con.close()
    assert "recalled_at" in cols, f"欄位未建立:{cols}"
