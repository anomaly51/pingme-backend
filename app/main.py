import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import admin, answers, auth, forms, reminders, study_tracking_router
from app.core.config import cors_allow_credentials, cors_origins, validate_production_config
from app.services.auth_service import run_auth_cleanup_scheduler
from app.services.health_service import check_database, check_rabbitmq
from app.services.reminder_service import run_reminder_scheduler
from app.services.tracking_service import run_find_offer_monthly_scheduler

from .sockets import sio


validate_production_config()
auth_cleanup_scheduler_task: asyncio.Task | None = None
find_offer_scheduler_task: asyncio.Task | None = None
reminder_scheduler_task: asyncio.Task | None = None


async def cancel_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global auth_cleanup_scheduler_task, find_offer_scheduler_task, reminder_scheduler_task

    auth_cleanup_scheduler_task = asyncio.create_task(run_auth_cleanup_scheduler())
    if os.getenv("REMINDER_SCHEDULER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        reminder_scheduler_task = None
    else:
        reminder_scheduler_task = asyncio.create_task(run_reminder_scheduler())
    if os.getenv("FIND_OFFER_AUTO_EXTEND", "").lower() not in {"1", "true", "yes"}:
        find_offer_scheduler_task = None
    else:
        find_offer_scheduler_task = asyncio.create_task(run_find_offer_monthly_scheduler())

    try:
        yield
    finally:
        await cancel_task(auth_cleanup_scheduler_task)
        await cancel_task(reminder_scheduler_task)
        await cancel_task(find_offer_scheduler_task)


fastapi_app = FastAPI(
    title="ping me Project API",
    description="FastAPI with PostgreSQL database.",
    version="0.1.0",
    lifespan=lifespan,
)


fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=cors_allow_credentials(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@fastapi_app.get("/", tags=["System Checks"])
async def root():
    """
    **Check server status.**
    """
    return {"message": "Server is running!"}


@fastapi_app.get("/health", tags=["System Checks"])
async def health():
    return {"status": "ok", "version": os.getenv("APP_VERSION", "")}


@fastapi_app.get("/health/live", tags=["System Checks"])
async def health_live():
    return {"status": "ok"}


@fastapi_app.get("/health/ready", tags=["System Checks"])
async def health_ready(response: Response):
    checks = {
        "database": await check_database(),
        "rabbitmq": await check_rabbitmq(),
    }
    is_ready = all(checks.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if is_ready else "degraded",
        "checks": checks,
        "version": os.getenv("APP_VERSION", ""),
    }


fastapi_app.include_router(auth.router)
fastapi_app.include_router(auth.users_router)
fastapi_app.include_router(forms.router)
fastapi_app.include_router(answers.router)
fastapi_app.include_router(reminders.router)
fastapi_app.include_router(admin.router)
fastapi_app.include_router(study_tracking_router.router)
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
