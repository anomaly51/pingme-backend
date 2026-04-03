from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import auth
from db.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield


app = FastAPI(
    title="ping me Project API",
    description="FastAPI with database PostgreSQL.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/", tags=["System Checks"])
async def root():
    """
    **Check server status.**
    """
    return {"message": "Server is running!"}


app.include_router(auth.router)
