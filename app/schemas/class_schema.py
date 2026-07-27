from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class ClassBase(BaseModel):
    name: str
    description: Optional[str] = None


class ClassCreate(ClassBase):
    pass


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ClassResponse(ClassBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    
    class Config:
        from_attributes = True


class SectionBase(BaseModel):
    name: str
    description: Optional[str] = None


class SectionCreate(SectionBase):
    pass


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class SectionResponse(SectionBase):
    id: UUID
    class_id: UUID
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

