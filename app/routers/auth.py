import os
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db

from ..models.user_model import BlockedToken, User
from ..schemas.user_schemas import UserCreate
from ..security import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_confirmation_token,
    get_current_user,
    get_password_hash,
    oauth2_scheme,
    verify_confirmation_token,
    verify_password,
)


router = APIRouter()


@router.post("/signup", status_code=status.HTTP_201_CREATED, tags=["Authorization"])
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.email == user_data.email)
    result = await db.execute(query)
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    hashed_pass = get_password_hash(user_data.password)

    new_user = User(email=user_data.email, hashed_password=hashed_pass)

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    confirmation_token = create_confirmation_token(new_user.email)

    base_url = os.getenv("APP_BASE_URL")
    confirmation_link = f"{base_url}/confirm-email/{confirmation_token}"

    print("\n--- SEND EMAIL ---")
    print(f"To: {new_user.email}")
    print("Subject: Confirm your email")
    print(f"Link: {confirmation_link}")
    print("-------------------------------\n")

    return {
        "message": "User registered. Check your email for confirmation.",
        "user_email": new_user.email,
    }


@router.get("/confirm-email/{token}", tags=["Authorization"])
async def confirm_email(token: str, db: AsyncSession = Depends(get_db)):
    email = verify_confirmation_token(token)

    if email == "expired":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The link has expired (more than 15 minutes have passed). Please register again."
            ),
        )
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or corrupted token."
        )

    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.is_email_confirmed:
        return {"message": "Email was already confirmed earlier!"}

    user.is_email_confirmed = True
    await db.commit()

    return {"message": "Email successfully confirmed! Now you can log in."}


@router.post("/login", tags=["Authorization"])
async def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
):

    query = select(User).where(User.email == form_data.username)
    result = await db.execute(query)
    user = result.scalars().first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not getattr(user, "is_email_confirmed", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not confirmed. Please check your email.",
        )

    access_token = create_access_token(data={"sub": form_data.username})

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout", tags=["Authorization"])
async def logout_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    expire_timestamp = payload.get("exp")

    expires_at = datetime.fromtimestamp(expire_timestamp, tz=UTC).replace(tzinfo=None)

    blocked_token = BlockedToken(token=token, expires_at=expires_at)
    db.add(blocked_token)
    await db.commit()

    return {"message": "Successfully logged out. Token invalidated."}


@router.get("/protected", tags=["Protected"])
async def protected_endpoint(user_email: str = Depends(get_current_user)):
    return {"message": f"Hello, {user_email}! This is a protected endpoint."}


@router.get("/protected-route", tags=["Protected Test"])
async def protected_route(user_email: str = Depends(get_current_user)):
    return {"message": "Secret data retrieved!", "user": user_email}
