import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app

# In-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(setup_db):
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Mock auth ──────────────────────────────────────────────────────────────
ADMIN_PRINCIPAL = {
    "valid": True,
    "user_id": 1,
    "username": "admin",
    "display_name": "Test Admin",
    "is_admin": True,
    "principal_type": "human",
}

AGENT_PRINCIPAL = {
    "valid": True,
    "user_id": 42,
    "username": "test-agent",
    "display_name": "Test Agent",
    "is_admin": False,
    "principal_type": "agent",
}


def mock_admin():
    return ADMIN_PRINCIPAL


def mock_agent():
    return AGENT_PRINCIPAL
