from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.exam import QuestionBank
from app.utils.constants import DifficultyLevel, QuestionType


class QuestionBankService:
    """Service for the teacher question bank."""

    @staticmethod
    def add_question(
        db: Session,
        teacher_id: UUID,
        question_text: str,
        question_type: QuestionType,
        difficulty_level: Optional[DifficultyLevel] = None,
        tags: Optional[List[str]] = None,
    ) -> QuestionBank:
        entry = QuestionBank(
            teacher_id=teacher_id,
            question_text=question_text,
            question_type=question_type.value,
            difficulty_level=difficulty_level.value if difficulty_level else None,
            tags=tags or [],
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def list_questions(
        db: Session,
        teacher_id: UUID,
        search: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[QuestionBank]:
        query = db.query(QuestionBank).filter(QuestionBank.teacher_id == teacher_id)
        if search:
            query = query.filter(QuestionBank.question_text.ilike(f"%{search}%"))
        if tag:
            query = query.filter(QuestionBank.tags.any(tag))
        return query.order_by(QuestionBank.created_at.desc()).limit(limit).all()
