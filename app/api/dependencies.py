from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_app_token
from app.models.user_model import BlockedToken, User
from app.services.auth_service import AuthService
from db.database import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
oauth2_optional_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await _get_user_from_token(token, db)


async def get_optional_current_user(
    token: str | None = Depends(oauth2_optional_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None

    return await _get_user_from_token(token, db)


async def _get_user_from_token(token: str, db: AsyncSession) -> User:  # noqa: C901
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_app_token(token)
        token_type = payload.get("type")
        if token_type == "refresh" or (token_type is not None and token_type != "access"):
            raise credentials_exception

        email: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        if email is None:
            raise credentials_exception

        if jti is None:
            raise credentials_exception
    except InvalidTokenError as e:
        raise credentials_exception from e

    blocked_result = await db.execute(
        select(BlockedToken).where(
            BlockedToken.token == jti,
            BlockedToken.expires_at > datetime.now(UTC),
        )
    )
    if blocked_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token has been revoked (logged out).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if not user:
        raise credentials_exception

    token_iat = payload.get("iat")
    if user.password_changed_at:
        if not token_iat:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password has been changed. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        password_changed_at = user.password_changed_at
        if password_changed_at.tzinfo is None:
            password_changed_at = password_changed_at.replace(tzinfo=UTC)

        token_issued_at = datetime.fromtimestamp(token_iat, tz=UTC)
        if token_issued_at < password_changed_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password has been changed. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


async def get_current_user_obj(user: User = Depends(get_current_user)) -> User:
    return user


class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)) -> User:
        if not any(role in (user.roles or []) for role in self.allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required one of roles: {', '.join(self.allowed_roles)}",
            )
        return user
