import asyncio
import os

import socketio
from fastapi import FastAPI

from app.api.v1.endpoints import answers, auth, forms, reminders, study_tracking_router
from app.services.auth_service import run_auth_cleanup_scheduler
from app.services.reminder_service import run_reminder_scheduler
from app.services.tracking_service import run_find_offer_monthly_scheduler

from .sockets import sio


app = FastAPI(
    title="ping me Project API",
    description="FastAPI with PostgreSQL database.",
    version="0.1.0",
)
auth_cleanup_scheduler_task: asyncio.Task | None = None
find_offer_scheduler_task: asyncio.Task | None = None
reminder_scheduler_task: asyncio.Task | None = None


@app.get("/", tags=["System Checks"])
async def root():
    """
    **Check server status.**
    """
    return {"message": "Server is running!"}


@app.get("/health", tags=["System Checks"])
async def health():
    return {"status": "ok", "version": os.getenv("APP_VERSION", "")}


@app.on_event("startup")
async def start_auth_cleanup_scheduler():
    global auth_cleanup_scheduler_task
    auth_cleanup_scheduler_task = asyncio.create_task(run_auth_cleanup_scheduler())


@app.on_event("shutdown")
async def stop_auth_cleanup_scheduler():
    if auth_cleanup_scheduler_task is None:
        return

    auth_cleanup_scheduler_task.cancel()
    try:
        await auth_cleanup_scheduler_task
    except asyncio.CancelledError:
        pass


@app.on_event("startup")
async def start_reminder_scheduler():
    global reminder_scheduler_task
    if os.getenv("REMINDER_SCHEDULER_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return

    reminder_scheduler_task = asyncio.create_task(run_reminder_scheduler())


@app.on_event("shutdown")
async def stop_reminder_scheduler():
    if reminder_scheduler_task is None:
        return

    reminder_scheduler_task.cancel()
    try:
        await reminder_scheduler_task
    except asyncio.CancelledError:
        pass


@app.on_event("startup")
async def start_find_offer_scheduler():
    global find_offer_scheduler_task
    if os.getenv("FIND_OFFER_AUTO_EXTEND", "").lower() not in {"1", "true", "yes"}:
        return

    find_offer_scheduler_task = asyncio.create_task(run_find_offer_monthly_scheduler())


@app.on_event("shutdown")
async def stop_find_offer_scheduler():
    if find_offer_scheduler_task is None:
        return

    find_offer_scheduler_task.cancel()
    try:
        await find_offer_scheduler_task
    except asyncio.CancelledError:
        pass


app.include_router(auth.router)
app.include_router(auth.users_router)
app.include_router(forms.router)
app.include_router(answers.router)
app.include_router(reminders.router)
app.include_router(study_tracking_router.router)
app = socketio.ASGIApp(sio, other_asgi_app=app)
