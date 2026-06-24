"""HTTP 請求記錄:每個請求產生一行 method/path/status,且不含 query(避免外洩 token)。"""

import logging

import pytest

pytestmark = pytest.mark.asyncio


async def test_request_is_logged_without_query(client, register_user, caplog):
    """下載端點帶 ?token= 時,log 只記 path、不含 token。"""
    token = await register_user("log@example.com", "Log")
    with caplog.at_level(logging.INFO, logger="chatweb"):
        # 不存在的附件 → 401/404 皆可,重點是請求有被記錄且不含 query。
        await client.get(f"/attachments/00000000-0000-0000-0000-000000000000?token={token}")

    msgs = [r.getMessage() for r in caplog.records if r.name == "chatweb"]
    assert any("/attachments/00000000-0000-0000-0000-000000000000 ->" in m for m in msgs)
    assert all(token not in m for m in msgs)  # token 不該出現在 log
    assert all("?" not in m for m in msgs)    # 完全不含 query string


async def test_health_request_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="chatweb"):
        await client.get("/health")
    msgs = [r.getMessage() for r in caplog.records if r.name == "chatweb"]
    assert any("GET /health -> 200" in m for m in msgs)
