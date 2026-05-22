from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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
    avatar_url: str | None = None
    push_token: str | None = None
    timezone: str = "UTC"
    notification_preferences: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(None, max_length=80)
    last_name: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, max_length=40)
    birth_date: str | None = Field(None, max_length=20)
    gender: str | None = Field(None, max_length=20)
    avatar_url: str | None = Field(None, max_length=500)
    push_token: str | None = Field(None, max_length=500)
    timezone: str | None = Field(None, max_length=64)
    notification_preferences: dict[str, bool] | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown timezone") from exc
        return value
