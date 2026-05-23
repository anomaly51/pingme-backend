import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/app_db"
)
SQL_ECHO = os.getenv("SQL_ECHO", "").lower() in {"1", "true", "yes"}

engine = create_async_engine(DATABASE_URL, echo=SQL_ECHO)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

SessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
