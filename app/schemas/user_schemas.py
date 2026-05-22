from pydantic import BaseModel, EmailStr

from ..schemas.password_schemas import StrongPassword


class UserCreate(BaseModel):
    email: EmailStr
    password: StrongPassword


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class GoogleLogin(BaseModel):
    id_token: str
