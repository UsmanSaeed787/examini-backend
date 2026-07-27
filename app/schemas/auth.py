from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthSchema(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenSchema(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetSchema(BaseModel):
    token: str
    new_password: str

