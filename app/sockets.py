import os
from datetime import UTC, datetime
from typing import Any

import socketio
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import cors_origins
from app.core.security import decode_app_token
from app.models.user_model import AuthSession, BlockedToken, User
from db.database import SessionLocal


socket_manager = None
if os.getenv("TESTING", "").lower() not in {"1", "true", "yes"}:
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

    jti = payload.get("jti")
    session_id = payload.get("sid")
    if not payload.get("sub") or not jti:
        return False

    async with SessionLocal() as db:
        user = await authenticated_socket_user(db, payload, jti, session_id)
    if user is None:
        return False

    await sio.enter_room(sid, f"user_{user.id}")


@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")


async def authenticated_socket_user(
    db: AsyncSession,
    payload: dict[str, Any],
    jti: str,
    session_id: str | None,
) -> User | None:
    result = await db.execute(select(User).where(User.email == payload.get("sub")))
    user = result.scalar_one_or_none()
    if user is None or not user.is_email_confirmed:
        return None

    if token_was_issued_before_password_change(payload, user):
        return None

    blocked_result = await db.execute(
        select(BlockedToken.id).where(
            BlockedToken.token == jti,
            BlockedToken.expires_at > datetime.now(UTC),
        )
    )
    if blocked_result.scalar_one_or_none() is not None:
        return None

    if session_id is not None and not await socket_session_is_active(db, session_id, user.id):
        return None

    return user


def token_was_issued_before_password_change(payload: dict[str, Any], user: User) -> bool:
    if user.password_changed_at is None:
        return False

    token_iat = payload.get("iat")
    if not token_iat:
        return True

    password_changed_at = user.password_changed_at
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=UTC)
    return datetime.fromtimestamp(token_iat, tz=UTC) < password_changed_at


async def socket_session_is_active(db: AsyncSession, session_id: str, user_id: int) -> bool:
    session_result = await db.execute(
        select(AuthSession.id).where(
            AuthSession.session_id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    return session_result.scalar_one_or_none() is not None
