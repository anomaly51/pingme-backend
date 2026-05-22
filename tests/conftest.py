import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


os.environ.setdefault("TESTING", "True")

from app.api.v1.endpoints import auth
from app.core.security import create_access_token, get_password_hash
from app.models.user_model import User
from db.database import Base, get_db


TEST_PASSWORD = "Strongpassword123"

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://test_user:test_password@localhost:5435/test_db"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
PROJECT_ROOT = Path(__file__).resolve().parents[1]

_engine = create_async_engine(TEST_DATABASE_URL, future=True)
_session_maker = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_db():
    async with _session_maker() as session:
        yield session


test_app = FastAPI()
test_app.include_router(auth.router)
test_app.include_router(auth.users_router)
test_app.dependency_overrides[get_db] = override_get_db


def run_alembic_upgrade(database_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def prepare_database():
    try:
        async with _engine.connect() as conn:
            result = await conn.execute(text("SELECT current_database();"))
            db_name = result.scalar()
    except Exception as exc:
        pytest.skip(f"Test database is not available: {exc}", allow_module_level=True)

    if db_name != "test_db":
        pytest.exit(f"Refusing to run auth tests against non-test database: {db_name}")

    async with _engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

    run_alembic_upgrade(TEST_DATABASE_URL)

    yield

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture()
async def async_client(prepare_database):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture()
async def db_session(prepare_database):
    async with _session_maker() as session:
        yield session


async def register_user(
    client: AsyncClient,
    email: str | None = None,
    password: str = TEST_PASSWORD,
) -> dict:
    email = email or f"u_{uuid.uuid4().hex[:8]}@test.com"
    response = await client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    data = response.json()
    return {"email": email, "password": password, "id": data["id"]}


async def login_user(client: AsyncClient, email: str, password: str = TEST_PASSWORD) -> dict:
    response = await client.post("/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    data = response.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "token_type": data["token_type"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


async def reg_and_login(
    client: AsyncClient,
    email: str | None = None,
    password: str = TEST_PASSWORD,
) -> dict:
    user = await register_user(client, email, password)
    session = await login_user(client, user["email"], password)
    return {**user, **session}


async def make_user_with_role(role: str) -> dict:
    async with _session_maker() as session:
        email = f"{role}_{uuid.uuid4().hex[:8]}@test.com"
        user = User(
            email=email,
            hashed_password=get_password_hash(TEST_PASSWORD),
            roles=[role],
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    access_token = create_access_token(data={"sub": email})
    return {
        "email": email,
        "password": TEST_PASSWORD,
        "id": user.id,
        "access_token": access_token,
        "headers": {"Authorization": f"Bearer {access_token}"},
    }


async def make_admin() -> dict:
    return await make_user_with_role("admin")


async def make_manager() -> dict:
    return await make_user_with_role("manager")


async def make_customer() -> dict:
    return await make_user_with_role("customer")
