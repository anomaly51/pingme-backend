from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import get_current_user, oauth2_scheme
from app.schemas.user_schemas import UserCreate
from app.services.auth_service import AuthService


router = APIRouter()


@router.post("/signup", status_code=status.HTTP_201_CREATED, tags=["Authorization"])
async def register_user(
    user_data: UserCreate,
    auth_service: AuthService = Depends(),
):
    return await auth_service.register_user(user_data)


@router.get("/confirm-email/{token}", tags=["Authorization"])
async def confirm_email(token: str, auth_service: AuthService = Depends()):
    return await auth_service.confirm_email(token)


@router.post("/login", tags=["Authorization"])
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(), auth_service: AuthService = Depends()
):
    return await auth_service.login_user(form_data.username, form_data.password)


@router.post("/logout", tags=["Authorization"])
async def logout_user(token: str = Depends(oauth2_scheme), auth_service: AuthService = Depends()):
    return await auth_service.logout_user(token)


@router.get("/protected", tags=["Protected"])
async def protected_endpoint(user_email: str = Depends(get_current_user)):
    return {"message": f"Hello, {user_email}! This is a protected endpoint."}


@router.get("/protected-route", tags=["Protected Test"])
async def protected_route(user_email: str = Depends(get_current_user)):
    return {"message": "Secret data retrieved!", "user": user_email}
