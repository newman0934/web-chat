import uuid

from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.conversations import direct_key


def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    uid = str(uuid.uuid4())
    token = create_access_token(uid)
    assert decode_access_token(token) == uid


def test_jwt_invalid_returns_none():
    assert decode_access_token("not.a.jwt") is None


def test_direct_key_is_stable():
    a = uuid.uuid4()
    b = uuid.uuid4()
    assert direct_key(a, b) == direct_key(b, a)
    key = direct_key(a, b)
    parts = key.split(":")
    assert len(parts) == 2
    assert parts[0] < parts[1]
