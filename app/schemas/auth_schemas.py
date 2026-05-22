from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    email: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(None, description="Refresh token to revoke too")


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(..., min_length=20)


class EmailVerificationCodeRequest(BaseModel):
    email: EmailStr


class EmailVerificationConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class AssignAdminRequest(BaseModel):
    email: EmailStr


class AssignManagerRequest(BaseModel):
    email: EmailStr
