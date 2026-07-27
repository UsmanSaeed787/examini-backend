from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class MaterialBase(BaseModel):
    title: str
    description: Optional[str] = None


class MaterialCreate(MaterialBase):
    class_id: UUID


class MaterialUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class MaterialResponse(MaterialBase):
    id: UUID
    teacher_id: UUID
    class_id: UUID
    file_url: str
    file_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_at: datetime
    updated_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True

