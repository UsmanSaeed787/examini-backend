from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal


class ExamResponseSave(BaseModel):
    question_id: UUID
    answer_text: Optional[str] = None
    selected_options: Optional[List[UUID]] = None


class ExamResponseResponse(BaseModel):
    id: UUID
    question_id: UUID
    answer_text: Optional[str] = None
    selected_options: Optional[List[UUID]] = None
    is_correct: Optional[bool] = None
    points_earned: Decimal
    
    class Config:
        from_attributes = True


class ExamSubmit(BaseModel):
    responses: List[ExamResponseSave]


class ExamAttemptResponse(BaseModel):
    id: UUID
    exam_id: UUID
    student_id: UUID
    started_at: datetime
    submitted_at: Optional[datetime] = None
    status: str
    time_spent_minutes: Optional[int] = None
    attempt_number: int
    
    class Config:
        from_attributes = True


class ExamResultResponse(BaseModel):
    id: UUID
    attempt_id: UUID
    total_score: Decimal
    max_score: Decimal
    percentage: Decimal
    grade: Optional[str] = None
    passed: Optional[bool] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class ResultDetailResponse(ExamResultResponse):
    attempt: ExamAttemptResponse
    responses: List[ExamResponseResponse]

