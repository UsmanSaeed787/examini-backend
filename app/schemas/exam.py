from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.utils.constants import QuestionType, DifficultyLevel


class QuestionOptionCreate(BaseModel):
    option_text: str
    is_correct: bool
    order_number: int


class QuestionOptionResponse(BaseModel):
    id: UUID
    option_text: str
    is_correct: bool
    order_number: int
    
    class Config:
        from_attributes = True


class QuestionCreate(BaseModel):
    question_text: str
    question_type: QuestionType
    difficulty_level: Optional[DifficultyLevel] = None
    points: float = 1.0
    order_number: int
    options: Optional[List[QuestionOptionCreate]] = None


class QuestionResponse(BaseModel):
    id: UUID
    question_text: str
    question_type: QuestionType
    difficulty_level: Optional[DifficultyLevel] = None
    points: float
    order_number: int
    options: Optional[List[QuestionOptionResponse]] = None
    
    class Config:
        from_attributes = True


class ExamBase(BaseModel):
    title: str
    description: Optional[str] = None
    duration_minutes: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class ExamCreate(ExamBase):
    class_id: UUID
    questions: List[QuestionCreate]
    allow_retake: bool = False
    max_attempts: int = 1


class ExamGenerate(BaseModel):
    title: str
    description: Optional[str] = None
    class_id: UUID
    material_ids: List[UUID]
    question_config: dict  # {total, easy, medium, hard, mcq, short_answer, long_answer}
    duration_minutes: int
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    allow_retake: bool = False
    max_attempts: int = 1


class ExamUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    duration_minutes: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    allow_retake: Optional[bool] = None
    max_attempts: Optional[int] = None


class ExamResponse(ExamBase):
    id: UUID
    teacher_id: UUID
    class_id: UUID
    is_published: bool
    allow_retake: bool
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ExamDetailResponse(ExamResponse):
    questions: List[QuestionResponse]
    
    class Config:
        from_attributes = True


class ExamPublish(BaseModel):
    is_published: bool


class ExamSectionAssign(BaseModel):
    section_ids: List[UUID]


class ExamPermissionUpdate(BaseModel):
    can_view_results: bool
    results_visible_to: str
    visible_from_date: Optional[datetime] = None

