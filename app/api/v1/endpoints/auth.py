from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import RoleChecker, get_auth_service, get_current_user, oauth2_scheme
from app.models.user_model import User
from app.schemas.auth_schemas import (
    AssignAdminRequest,
    AssignManagerRequest,
    GoogleLoginRequest,
    LogoutRequest,
    RefreshRequest,
    Token,
)
from app.schemas.password_schemas import ChangePasswordRequest, PasswordResetRequest
from app.schemas.user_schemas import UserCreate, UserProfileUpdate, UserResponse
from app.services.auth_service import AuthService
from db.database import get_db


router = APIRouter(prefix="/auth", tags=["Authorization"])
users_router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user_data: UserCreate,
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.register_user(user_data)


@router.get("/verify-email/{token}")
async def confirm_email(token: str, auth_service: AuthService = Depends(get_auth_service)):
    return await auth_service.confirm_email(token)


@router.post("/login", response_model=Token)
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.login_user(form_data.username, form_data.password)


@router.post("/google", response_model=Token)
async def google_login(
    data: GoogleLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    user = await auth_service.authenticate_google_user(data.id_token)
    return auth_service._token_pair(user.email)


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    data: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    return await auth_service.refresh_access_token(data.refresh_token)


@router.post("/logout")
async def logout_user(
    data: LogoutRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    auth_header = request.headers.get("Authorization", "")
    access_token = auth_header.removeprefix("Bearer ").strip()
    await auth_service.logout(access_token=access_token, refresh_token=data.refresh_token)
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
async def request_password_reset(data: PasswordResetRequest):
    return {
        "detail": (
            "Если аккаунт существует, инструкция по восстановлению будет отправлена на email."
        ),
        "email": str(data.email).lower(),
    }


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
