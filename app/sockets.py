import os

import socketio
from jwt import PyJWTError
from sqlalchemy import select

from app.core.config import cors_origins
from app.core.security import decode_app_token
from app.models.user_model import User
from db.database import SessionLocal


socket_manager = None
if os.getenv("TESTING") != "True":
    socket_manager = socketio.AsyncAioPikaManager(
        os.getenv("RABBITMQ_SOCKETIO_URL")
        or os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    )

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=cors_origins(),
    client_manager=socket_manager,
)


@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token") or (auth or {}).get("access_token")
    if not token:
        return False

    try:
        payload = decode_app_token(token)
    except PyJWTError:
        return False

    if payload.get("type") != "access":
        return False

    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email == payload.get("sub")))
        user = result.scalar_one_or_none()

    if user is None:
        return False

    await sio.enter_room(sid, f"user_{user.id}")


@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
