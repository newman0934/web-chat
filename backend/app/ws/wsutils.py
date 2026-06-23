"""WS handler 共用小工具（純函式，無 IO）。"""

import uuid
from datetime import datetime, timezone


def parse_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def as_utc(dt: datetime) -> datetime:
    """把可能為 naive 的 datetime 視為 UTC，供時窗比較。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
