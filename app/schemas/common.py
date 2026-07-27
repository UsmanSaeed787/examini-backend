from pydantic import BaseModel
from typing import List, Generic, TypeVar, Optional

T = TypeVar('T')


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    limit: int
    pages: int


class MessageResponse(BaseModel):
    message: str


class DashboardStats(BaseModel):
    total_users: Optional[int] = None
    total_teachers: Optional[int] = None
    total_students: Optional[int] = None
    total_classes: Optional[int] = None
    total_exams: Optional[int] = None
    total_materials: Optional[int] = None
    available_exams: Optional[int] = None
    completed_exams: Optional[int] = None
    upcoming_exams: Optional[List] = None
    recent_exams: Optional[List] = None
    recent_results: Optional[List] = None

