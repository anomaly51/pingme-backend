import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/app_db"
)

engine = create_async_engine(DATABASE_URL, echo=True)

async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
