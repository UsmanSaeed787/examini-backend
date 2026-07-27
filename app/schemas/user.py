from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.utils.constants import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: UUID
    email_verified: bool
    is_active: bool
    profile_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserDetail(UserResponse):
    profile_image_url: Optional[str] = None
    google_id: Optional[str] = None


class StudentCreate(UserBase):
    password: str
    class_id: UUID
    section_id: UUID


class BulkUserCreate(BaseModel):
    users: list[UserCreate]

