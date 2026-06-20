"""回歸測試：Alembic 0002 遷移產生的 direct_key 必須與 app 的 direct_key() 一致。

防的 bug：SQLite 把 Uuid 存成無連字號的 32 字元 hex，遷移若直接 str() 會得到無連字號
的 key，與 app（用 uuid.UUID → 帶連字號）算出的 key 不符，導致遷移後重複建立 direct 對話。
本測試實際跑 alembic upgrade（0001 → 0002），不重寫搬移邏輯。
"""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

from app.services.conversations import direct_key

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, revision: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade {revision} failed:\n{result.stderr}"


def test_migration_0002_direct_key_matches_app(tmp_path):
    db = tmp_path / "mig.db"

    # 1) 升到舊 schema 0001
    _alembic(db, "0001")

    # 2) 以「SQLite 儲存樣式」(無連字號 hex) 塞入兩位 user 與一筆 direct 對話
    a_hex = uuid.uuid4().hex
    b_hex = uuid.uuid4().hex
    conv_hex = uuid.uuid4().hex
    raw = sqlite3.connect(db)
    raw.execute(
        "INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
        (a_hex, "a@x.com", "A", "h"),
    )
    raw.execute(
        "INSERT INTO users (id, email, display_name, password_hash) VALUES (?,?,?,?)",
        (b_hex, "b@x.com", "B", "h"),
    )
    raw.execute(
        "INSERT INTO conversations (id, user_a_id, user_b_id) VALUES (?,?,?)",
        (conv_hex, a_hex, b_hex),
    )
    raw.commit()
    raw.close()

    # 3) 升到 0002（觸發資料搬移）
    _alembic(db, "head")

    # 4) 驗證：搬移後的 direct_key 與 app 算出的一致，且只有一筆對話、兩位成員
    check = sqlite3.connect(db)
    rows = check.execute("SELECT id, type, direct_key FROM conversations").fetchall()
    assert len(rows) == 1
    _, conv_type, migrated_key = rows[0]
    assert conv_type == "direct"

    expected_key = direct_key(uuid.UUID(a_hex), uuid.UUID(b_hex))
    assert migrated_key == expected_key, (
        f"migrated key {migrated_key!r} != app key {expected_key!r}"
    )

    member_count = check.execute(
        "SELECT COUNT(*) FROM conversation_members WHERE conversation_id=?", (conv_hex,)
    ).fetchone()[0]
    assert member_count == 2
    check.close()
