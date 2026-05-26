import asyncio
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

import jwt
from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select, update
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
from app.models.user_model import AuthSession, BlockedToken, EmailAuthCode, User
from app.schemas.user_schemas import UserCreate
from app.services.email_service import send_email_verification_code, send_password_reset_code
from db.database import SessionLocal, get_db


EMAIL_VERIFICATION_PURPOSE = "email_verification"
PASSWORD_RESET_PURPOSE = "password_reset"
AUTH_CODE_EXPIRE_MINUTES = 15
AUTH_CODE_MAX_ATTEMPTS = 5
CLEANUP_INTERVAL_SECONDS = 60 * 60


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
        await self.send_email_verification_code(user.email)
        return user

    async def authenticate_user(self, email: str, password: str) -> User | None:
        user = await self._get_user_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    async def login_user(self, email: str, password: str) -> dict[str, str]:
        await self.cleanup_expired_blocked_tokens()
        user = await self.authenticate_user(email, password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_email_confirmed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email is not confirmed",
            )

        return await self._token_pair(user)

    async def authenticate_google_user(self, id_token: str) -> User:
        google_client_ids = self._google_client_ids()
        if not google_client_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Вход через Google не настроен",
            )

        payload = await asyncio.to_thread(self._verify_google_id_token, id_token, google_client_ids)
        if payload.get("aud") not in google_client_ids:
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
            if not user.is_email_confirmed:
                user.is_email_confirmed = True
                self.db.add(user)
                await self.db.commit()
                await self.db.refresh(user)
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
    def _google_client_ids() -> list[str]:
        raw_client_ids = os.getenv("GOOGLE_CLIENT_IDS") or os.getenv("GOOGLE_CLIENT_ID", "")
        return [client_id.strip() for client_id in raw_client_ids.split(",") if client_id.strip()]

    @staticmethod
    def _verify_google_id_token(id_token: str, google_client_ids: list[str]) -> dict:
        if google_id_token is not None and google_requests is not None:
            last_error: Exception | None = None
            for google_client_id in google_client_ids:
                try:
                    return google_id_token.verify_oauth2_token(
                        id_token,
                        google_requests.Request(),
                        google_client_id,
                    )
                except Exception as exc:
                    last_error = exc
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный Google token",
            ) from last_error

        query = urlencode({"id_token": id_token})
        try:
            with urlopen(f"https://oauth2.googleapis.com/tokeninfo?{query}", timeout=5) as res:
                return json.loads(res.read().decode("utf-8"))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный Google token",
            ) from exc

    async def send_email_verification_code(self, email: str) -> dict[str, str]:
        user = await self._get_user_by_email(email)
        if user and not user.is_email_confirmed:
            target_email = user.email
            code = await self._create_auth_code(target_email, EMAIL_VERIFICATION_PURPOSE)
            try:
                await asyncio.to_thread(send_email_verification_code, target_email, code)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Не удалось отправить код подтверждения email",
                ) from exc

        return {"detail": "Если аккаунт существует, код подтверждения будет отправлен на email."}

    async def confirm_email_code(self, email: str, code: str) -> dict[str, str]:
        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        if not await self._consume_auth_code(user.email, EMAIL_VERIFICATION_PURPOSE, code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        user.is_email_confirmed = True
        self.db.add(user)
        await self.db.commit()
        return {"message": "Email confirmed successfully"}

    async def request_password_reset(self, email: str) -> dict[str, str]:
        user = await self._get_user_by_email(email)
        if user:
            target_email = user.email
            code = await self._create_auth_code(target_email, PASSWORD_RESET_PURPOSE)
            try:
                await asyncio.to_thread(send_password_reset_code, target_email, code)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Не удалось отправить код восстановления пароля",
                ) from exc

        return {
            "detail": (
                "Если аккаунт существует, инструкция по восстановлению будет отправлена на email."
            )
        }

    async def confirm_password_reset(
        self, email: str, code: str, new_password: str
    ) -> dict[str, str]:
        user = await self._get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        if not await self._consume_auth_code(user.email, PASSWORD_RESET_PURPOSE, code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")

        user.hashed_password = get_password_hash(new_password)
        user.password_changed_at = datetime.now(UTC)
        self.db.add(user)
        await self.db.commit()
        return {"detail": "Пароль успешно изменён"}

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
        await self.cleanup_expired_blocked_tokens()
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
        session_id = payload.get("sid")
        if not email or not jti or not session_id:
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
        session = await self._get_active_session(session_id, user.id)
        if not session or session.refresh_jti != jti:
            await self._revoke_session_by_id(session_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        blocked = await self._get_blocked_token(jti)
        if blocked:
            await self._revoke_session(session)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Этот refresh token был отозван или уже использован. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        blocked_current_refresh = await self._block_jti(
            jti,
            datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
        if not blocked_current_refresh:
            await self._revoke_session(session)
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected. Авторизуйтесь заново.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await self.db.commit()
        return await self._token_pair(user, session=session)

    async def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        await self.cleanup_expired_blocked_tokens()
        for token, expected_type in ((access_token, "access"), (refresh_token, "refresh")):
            if not token:
                continue
            record = self._token_block_record(token, expected_type)
            if record is None:
                continue
            jti, expires_at = record
            if not await self._get_blocked_token(jti):
                await self._block_jti(jti, expires_at)
            await self._revoke_session_by_token(token)

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

    async def cleanup_expired_blocked_tokens(self) -> int:
        result = await self.db.execute(
            delete(BlockedToken).where(BlockedToken.expires_at <= datetime.now(UTC))
        )
        await self.db.commit()
        return result.rowcount or 0

    async def cleanup_expired_auth_codes(self) -> int:
        result = await self.db.execute(
            delete(EmailAuthCode).where(EmailAuthCode.expires_at <= datetime.now(UTC))
        )
        await self.db.commit()
        return result.rowcount or 0

    async def cleanup_expired_auth_sessions(self) -> int:
        result = await self.db.execute(
            delete(AuthSession).where(AuthSession.expires_at <= datetime.now(UTC))
        )
        await self.db.commit()
        return result.rowcount or 0

    async def list_sessions(self, user: User, current_token: str | None = None) -> list[dict]:
        current_session_id = None
        if current_token:
            try:
                current_session_id = decode_app_token(current_token).get("sid")
            except jwt.PyJWTError:
                current_session_id = None

        result = await self.db.execute(
            select(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
            .order_by(AuthSession.last_used_at.desc())
        )
        return [
            {
                "session_id": session.session_id,
                "created_at": session.created_at.isoformat(),
                "last_used_at": session.last_used_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "current": session.session_id == current_session_id,
            }
            for session in result.scalars().all()
        ]

    async def revoke_session(self, user: User, session_id: str) -> dict[str, str]:
        session = await self._get_active_session(session_id, user.id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        await self._revoke_session(session)
        await self.db.commit()
        return {"detail": "Session revoked"}

    async def revoke_other_sessions(self, user: User, current_token: str) -> dict[str, str]:
        current_session_id = decode_app_token(current_token).get("sid")
        now = datetime.now(UTC)
        await self.db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.session_id != current_session_id,
            )
            .values(revoked_at=now)
        )
        await self.db.commit()
        return {"detail": "Other sessions revoked"}

    async def _create_auth_code(self, email: str, purpose: str) -> str:
        await self.cleanup_expired_auth_codes()
        normalized_email = str(email).lower()
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = datetime.now(UTC)

        await self.db.execute(
            update(EmailAuthCode)
            .where(
                EmailAuthCode.email == normalized_email,
                EmailAuthCode.purpose == purpose,
                EmailAuthCode.used_at.is_(None),
            )
            .values(used_at=now)
        )
        self.db.add(
            EmailAuthCode(
                email=normalized_email,
                purpose=purpose,
                code_hash=get_password_hash(code),
                attempts=0,
                expires_at=now + timedelta(minutes=AUTH_CODE_EXPIRE_MINUTES),
            )
        )
        await self.db.commit()
        return code

    async def _consume_auth_code(self, email: str, purpose: str, code: str) -> bool:
        await self.cleanup_expired_auth_codes()
        normalized_email = str(email).lower()
        result = await self.db.execute(
            select(EmailAuthCode)
            .where(
                EmailAuthCode.email == normalized_email,
                EmailAuthCode.purpose == purpose,
                EmailAuthCode.used_at.is_(None),
                EmailAuthCode.expires_at > datetime.now(UTC),
            )
            .order_by(EmailAuthCode.created_at.desc(), EmailAuthCode.id.desc())
        )
        auth_code = result.scalars().first()
        if not auth_code:
            return False

        if not verify_password(code, auth_code.code_hash):
            auth_code.attempts += 1
            if auth_code.attempts >= AUTH_CODE_MAX_ATTEMPTS:
                auth_code.used_at = datetime.now(UTC)
            self.db.add(auth_code)
            await self.db.commit()
            return False

        auth_code.used_at = datetime.now(UTC)
        self.db.add(auth_code)
        await self.db.commit()
        return True

    async def _block_jti(self, jti: str, expires_at: datetime) -> bool:
        if await self._get_blocked_token(jti):
            return False

        try:
            async with self.db.begin_nested():
                self.db.add(BlockedToken(token=jti, expires_at=expires_at))
                await self.db.flush()
        except IntegrityError:
            return False
        return True

    async def _token_pair(self, user: User, session: AuthSession | None = None) -> dict[str, str]:
        session_id = session.session_id if session else uuid.uuid4().hex
        data = {"sub": user.email, "sid": session_id}
        access_token = create_access_token(data=data)
        refresh_token = create_refresh_token(data=data)
        refresh_payload = decode_app_token(refresh_token)
        refresh_jti = refresh_payload["jti"]
        expires_at = datetime.fromtimestamp(refresh_payload["exp"], tz=UTC)

        if session is None:
            session = AuthSession(
                session_id=session_id,
                user_id=user.id,
                refresh_jti=refresh_jti,
                expires_at=expires_at,
                last_used_at=datetime.now(UTC),
            )
        else:
            session.refresh_jti = refresh_jti
            session.expires_at = expires_at
            session.last_used_at = datetime.now(UTC)

        self.db.add(session)
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
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

    async def _get_active_session(self, session_id: str, user_id: int) -> AuthSession | None:
        result = await self.db.execute(
            select(AuthSession).where(
                AuthSession.session_id == session_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()

    async def _revoke_session(self, session: AuthSession) -> None:
        session.revoked_at = datetime.now(UTC)
        self.db.add(session)

    async def _revoke_session_by_id(self, session_id: str) -> None:
        await self.db.execute(
            update(AuthSession)
            .where(AuthSession.session_id == session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.db.commit()

    async def _revoke_session_by_token(self, token: str) -> None:
        try:
            payload = decode_app_token(token)
        except jwt.PyJWTError:
            return

        session_id = payload.get("sid")
        if session_id:
            await self.db.execute(
                update(AuthSession)
                .where(AuthSession.session_id == session_id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )

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


async def run_auth_cleanup_scheduler() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                service = AuthService(db)
                await service.cleanup_expired_blocked_tokens()
                await service.cleanup_expired_auth_codes()
                await service.cleanup_expired_auth_sessions()
        except Exception:
            pass

        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
