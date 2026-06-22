"""跨資料庫的 datetime 游標處理。

DateTime(timezone=True) 欄位:Postgres 回 tz-aware、SQLite 回 naive。
分頁游標 before 由前端把回傳的 created_at 原樣帶回(現在一律為 aware UTC ISO),
查詢時須把它調成與「該方言實際儲存的欄位」可比較的形狀,否則:
  - SQLite(naive 欄位)拿到 aware 參數 → bind/比較錯誤。
  - Postgres(aware 欄位)拿到 naive 參數 → asyncpg 需要 aware。
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession


def to_utc_iso(dt: datetime | None) -> str | None:
    """序列化成 tz-aware UTC ISO 字串(WS / dict 推播用)。

    naive(SQLite)視為 UTC 並補時區;aware(Postgres)原樣。不可用
    `.astimezone(timezone.utc)` —— 那會把 naive 當「本機時間」換算,在非 UTC 機器上錯位。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def coerce_cursor(db: AsyncSession, dt: datetime | None) -> datetime | None:
    """把游標 datetime 調成與目前方言欄位可比較的形狀(UTC 基準)。"""
    if dt is None:
        return None
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "sqlite":
        # 欄位為 naive UTC:把 aware 轉成 UTC 後去除時區。
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    # Postgres(timestamptz)等:確保 aware。
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
