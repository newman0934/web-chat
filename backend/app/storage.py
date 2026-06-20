"""上傳檔案的本機儲存：隨機檔名、寫入 / 讀取，路徑來自 settings.upload_dir。"""

import uuid
from pathlib import Path

from app.config import get_settings


def _base_dir() -> Path:
    return Path(get_settings().upload_dir)


def make_stored_name(original_name: str) -> str:
    """隨機 uuid + 原副檔名，避免衝突與路徑穿越。"""
    ext = Path(original_name).suffix
    return f"{uuid.uuid4().hex}{ext}"


def save_bytes(stored_name: str, data: bytes) -> None:
    base = _base_dir()
    base.mkdir(parents=True, exist_ok=True)
    (base / stored_name).write_bytes(data)


def stored_path(stored_name: str) -> Path:
    return _base_dir() / stored_name
