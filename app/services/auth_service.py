import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

import jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token
except ImportError:
    google_id_token = None
    google_requests = None

from app.core.security import (
    create_access_token,
    create_confirmation_token,
    create_refresh_token,
    decode_app_token,
    get_password_hash,
    verify_confirmation_token,
    verify_password,
)
from app.models.user_model import BlockedToken, User
from app.schemas.user_schemas import UserCreate
from db.database import get_db


class AuthService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def register_user(self, user_data: UserCreate) -> User:
        email = str(user_data.email).lower()
        existing_user = await self._get_user_by_email(email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким email уже существует",
            )

        user = User(
            email=email,
            hashed_password=get_password_hash(user_data.password),
            roles=["customer"],
        )
        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким email уже существует",
            ) from exc

        await self.db.refresh(user)
        return user

    async def authenticate_user(self, email: str, password: str) -> User | None:
        user = await self._get_user_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    async def login_user(self, email: str, password: str) -> dict[str, str]:
        user = await self.authenticate_user(email, password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return self._token_pair(user.email)

    async def authenticate_google_user(self, id_token: str) -> User:
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        if not google_client_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вход через Google не настроен",
            )

        payload = await asyncio.to_thread(self._verify_google_id_token, id_token, google_client_id)
        if payload.get("aud") != google_client_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google token выпущен для другого приложения",
            )

        if payload.get("email_verified") not in (True, "true", "True"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google email не подтвержден",
            )

        email = str(payload.get("email", "")).strip().lower()
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google token не содержит email",
            )

        user = await self._get_user_by_email(email)
        if user:
            return user

        user = User(
            email=email,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            is_email_confirmed=True,
            roles=["customer"],
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    @staticmethod
    def _verify_google_id_token(id_token: str, google_client_id: str) -> dict:
        if google_id_token is not None and google_requests is not None:
            try:
                return google_id_token.verify_oauth2_token(
                    id_token,
                    google_requests.Request(),
                    google_client_id,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Невалидный Google token",
                ) from exc

        query = urlencode({"id_token": id_token})
        try:
            with urlopen(f"https://oauth2.googleapis.com/tokeninfo?{query}", timeout=5) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный Google token",
            ) from exc

    async def confirm_email(self, token: str) -> dict[str, str]:
        email = verify_confirmation_token(token)
        if email == "expired":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expired")
        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user.is_email_confirmed = True
        self.db.add(user)
        await self.db.commit()
        return {"message": "Email confirmed successfully"}

    async def assign_admin_role(self, email: str) -> User:
        user = await self._get_existing_user(email)
        roles = set(user.roles or [])
        roles.update({"admin", "manager"})
        user.roles = sorted(roles)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def assign_manager_role(self, email: str) -> User:
        user = await self._get_existing_user(email)
        roles = set(user.roles or [])
        roles.add("manager")
        user.roles = sorted(roles)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def change_password(self, user: User, old_password: str, new_password: str) -> None:
        if not verify_password(old_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный текущий пароль",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user.hashed_password = get_password_hash(new_password)
        user.password_changed_at = datetime.now(UTC)
        self.db.add(user)
        await self.db.commit()

    async def refresh_access_token(self, refresh_token: str) -> dict[str, str]:
        try:
            payload = decode_app_token(refresh_token)
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный или истёкший refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный тип токена. Ожидался refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        email = payload.get("sub")
        jti = payload.get("jti")
        if not email or not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token не содержит обязательные claims",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пользователь не найден",
                headers={"WWW-Authenticate": "Bearer"},
            )

        self._ensure_token_is_new_enough(payload, user)
        blocked = await self._get_blocked_token(jti)
        if blocked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Этот refresh token был отозван или уже использован. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        await self._block_jti(jti, datetime.fromtimestamp(payload["exp"], tz=UTC))
        await self.db.commit()
        return self._token_pair(user.email)

    async def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        for token, expected_type in ((access_token, "access"), (refresh_token, "refresh")):
            if not token:
                continue
            record = self._token_block_record(token, expected_type)
            if record is None:
                continue
            jti, expires_at = record
            if not await self._get_blocked_token(jti):
                await self._block_jti(jti, expires_at)

        await self.db.commit()

    async def logout_user(self, token: str) -> dict[str, str]:
        await self.logout(access_token=token)
        return {"detail": "Выход выполнен успешно"}

    async def _get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == str(email).lower()))
        return result.scalar_one_or_none()

    async def _get_existing_user(self, email: str) -> User:
        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким email не найден",
            )
        return user

    async def _get_blocked_token(self, jti: str) -> BlockedToken | None:
        result = await self.db.execute(select(BlockedToken).where(BlockedToken.token == jti))
        return result.scalar_one_or_none()

    async def _block_jti(self, jti: str, expires_at: datetime) -> None:
        self.db.add(BlockedToken(token=jti, expires_at=expires_at))
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()

    @staticmethod
    def _token_pair(email: str) -> dict[str, str]:
        return {
            "access_token": create_access_token(data={"sub": email}),
            "refresh_token": create_refresh_token(data={"sub": email}),
            "token_type": "bearer",
        }

    @staticmethod
    def _token_block_record(token: str, expected_type: str) -> tuple[str, datetime] | None:
        try:
            payload = decode_app_token(token)
        except jwt.PyJWTError:
            return None

        if payload.get("type") != expected_type or not payload.get("jti"):
            return None

        return payload["jti"], datetime.fromtimestamp(payload["exp"], tz=UTC)

    @staticmethod
    def _ensure_token_is_new_enough(payload: dict, user: User) -> None:
        if not user.password_changed_at:
            return

        token_iat = payload.get("iat")
        if not token_iat:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пароль был изменен. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        password_changed_at = user.password_changed_at
        if password_changed_at.tzinfo is None:
            password_changed_at = password_changed_at.replace(tzinfo=UTC)

        token_issued_at = datetime.fromtimestamp(token_iat, tz=UTC)
        if token_issued_at < password_changed_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Пароль был изменен. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )


def create_email_confirmation_link(email: str) -> str:
    app_base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = create_confirmation_token(email)
    return f"{app_base_url}/auth/verify-email/{token}"
