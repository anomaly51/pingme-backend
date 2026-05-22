import os

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import RoleChecker, get_auth_service, get_current_user, oauth2_scheme
from app.api.rate_limit import rate_limit
from app.models.user_model import User
from app.schemas.auth_schemas import (
    AssignAdminRequest,
    AssignManagerRequest,
    AuthSessionResponse,
    EmailVerificationCodeRequest,
    EmailVerificationConfirmRequest,
    GoogleLoginRequest,
    LogoutRequest,
    RefreshRequest,
    Token,
)
from app.schemas.password_schemas import (
    ChangePasswordRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.schemas.user_schemas import UserCreate, UserProfileUpdate, UserResponse
from app.services.auth_service import AuthService
from db.database import get_db


router = APIRouter(prefix="/auth", tags=["Authorization"])
users_router = APIRouter(prefix="/users", tags=["Users"])
REFRESH_COOKIE_NAME = "refresh_token"


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
        samesite=os.getenv("COOKIE_SAMESITE", "lax"),
        max_age=int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")) * 24 * 60 * 60,
        path="/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_data: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("register", limit=10, window_seconds=300)),
):
    return await auth_service.register_user(user_data)


@router.get("/verify-email/{token}")
async def confirm_email(token: str, auth_service: AuthService = Depends(get_auth_service)):
    return await auth_service.confirm_email(token)


@router.post("/verify-email/request")
async def request_email_verification_code(
    data: EmailVerificationCodeRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("verify_email_request", limit=5, window_seconds=300)),
):
    return await auth_service.send_email_verification_code(str(data.email).lower())


@router.post("/verify-email/confirm")
async def confirm_email_code(
    data: EmailVerificationConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("verify_email_confirm", limit=10, window_seconds=300)),
):
    return await auth_service.confirm_email_code(str(data.email).lower(), data.code)


@router.post("/login", response_model=Token)
async def login_user(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("login", limit=10, window_seconds=300)),
):
    tokens = await auth_service.login_user(form_data.username, form_data.password)
    set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/google", response_model=Token)
async def google_login(
    data: GoogleLoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("google_login", limit=20, window_seconds=300)),
):
    user = await auth_service.authenticate_google_user(data.id_token)
    tokens = await auth_service._token_pair(user)
    set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    data: RefreshRequest | None = None,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("refresh", limit=30, window_seconds=300)),
):
    refresh_token = data.refresh_token if data else None
    refresh_token = refresh_token or request.cookies.get(REFRESH_COOKIE_NAME)
    tokens = await auth_service.refresh_access_token(refresh_token or "")
    set_refresh_cookie(response, tokens["refresh_token"])
    return tokens


@router.post("/logout")
async def logout_user(
    data: LogoutRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()
    refresh_token = data.refresh_token or request.cookies.get(REFRESH_COOKIE_NAME)
    await auth_service.logout(access_token=access_token, refresh_token=refresh_token)
    clear_refresh_cookie(response)
    return {"detail": "Выход выполнен успешно", "user": current_user.email}


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    await auth_service.change_password(current_user, data.old_password, data.new_password)
    return {"detail": "Пароль успешно изменён"}


@router.post("/password-reset/request")
async def request_password_reset(
    data: PasswordResetRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("password_reset_request", limit=5, window_seconds=300)),
):
    return await auth_service.request_password_reset(str(data.email).lower())


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    data: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(get_auth_service),
    _rate_limit: None = Depends(rate_limit("password_reset_confirm", limit=10, window_seconds=300)),
):
    return await auth_service.confirm_password_reset(
        str(data.email).lower(), data.code, data.new_password
    )


@router.get("/sessions", response_model=list[AuthSessionResponse])
async def get_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()
    return await auth_service.list_sessions(current_user, access_token)


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.revoke_session(current_user, session_id)


@router.delete("/sessions")
async def revoke_other_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()
    return await auth_service.revoke_other_sessions(current_user, access_token)


@router.post("/assign-admin", response_model=UserResponse)
async def assign_admin(
    data: AssignAdminRequest,
    current_user: User = Depends(RoleChecker(["admin"])),
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.assign_admin_role(str(data.email).lower())


@router.post("/assign-manager", response_model=UserResponse)
async def assign_manager(
    data: AssignManagerRequest,
    current_user: User = Depends(RoleChecker(["admin"])),
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.assign_manager_role(str(data.email).lower())


@router.get("/me", response_model=UserResponse, tags=["Users"])
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    return current_user


@users_router.get("/me", response_model=UserResponse)
async def get_current_user_profile_legacy(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse, tags=["Users"])
async def update_current_user_profile(
    data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "notification_preferences" and value is not None:
            current = current_user.notification_preferences or {}
            value = {**current, **value}
        setattr(current_user, key, value)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("/me/secrets", tags=["Users"])
async def protected_route(current_user: User = Depends(get_current_user)):
    return {"message": "Secret data retrieved!", "user": current_user.email}


@users_router.get("/me/secrets")
async def protected_route_legacy(current_user: User = Depends(get_current_user)):
    return {"message": "Secret data retrieved!", "user": current_user.email}


@router.post("/logout-legacy", include_in_schema=False)
async def logout_legacy(
    token: str = Depends(oauth2_scheme),
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.logout_user(token)
