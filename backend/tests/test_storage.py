import re

from app import storage
from app.config import get_settings


def test_make_stored_name_is_random_with_ext():
    name = storage.make_stored_name("photo.PNG")
    assert re.fullmatch(r"[0-9a-f]{32}\.PNG", name)
    assert name != storage.make_stored_name("photo.PNG")


def test_save_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    stored = storage.make_stored_name("a.txt")
    storage.save_bytes(stored, b"hello")
    assert storage.stored_path(stored).read_bytes() == b"hello"
