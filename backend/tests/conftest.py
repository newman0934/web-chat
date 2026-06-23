import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import db as db_module
from app.db import Base, get_db
from app.main import app


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    # 用檔案型 SQLite + NullPool：每個 session 在自己的 event loop 取得新連線，
    # 讓 async REST client（pytest-asyncio loop）與 sync TestClient（WS）能共用資料。
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    original = db_module.SessionLocal
    db_module.SessionLocal = factory  # WS 端點直接用 db_module.SessionLocal
    yield factory
    db_module.SessionLocal = original


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_ws_singletons():
    """每個測試前後清空 WS 程序級單例(manager 連線、presence 快取)。

    manager 與 presence 快取是 module 級全域,跨測試會殘留上一個 TestClient 的(已關閉)
    websocket;後續測試的 presence 廣播若送到殘留連線會卡死。逐測重置確保隔離。
    """
    from app.ws import router as ws_router
    from app.ws.manager import manager

    manager._connections.clear()
    manager._last_seen.clear()
    ws_router._presence_cache.clear()
    yield
    manager._connections.clear()
    manager._last_seen.clear()
    ws_router._presence_cache.clear()


@pytest.fixture
def auth_headers():
    def _make(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest_asyncio.fixture
async def register_user(client):
    async def _make(email: str, name: str, pw: str = "secret123") -> str:
        resp = await client.post(
            "/auth/register",
            json={"email": email, "display_name": name, "password": pw},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["access_token"]

    return _make
