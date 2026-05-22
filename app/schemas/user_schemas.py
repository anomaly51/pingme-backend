from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.password_schemas import StrongPassword


class UserRole(StrEnum):
    CUSTOMER = "customer"
    MANAGER = "manager"
    ADMIN = "admin"


class UserBase(BaseModel):
    email: EmailStr


class UserCreate(UserBase):
    password: StrongPassword


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: int
    is_email_confirmed: bool
    roles: list[str]
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    birth_date: str | None = None
    gender: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(None, max_length=80)
    last_name: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, max_length=40)
    birth_date: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, max_length=20)
