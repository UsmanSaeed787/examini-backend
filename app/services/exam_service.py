from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional
from app.models.exam import Exam, Question, QuestionOption, ExamSection
from app.models.attempt import ExamPermission
from app.schemas.exam import ExamCreate, ExamUpdate
from app.middleware.error_handler import NotFoundError


class ExamService:
    """Service for exam management."""
    
    @staticmethod
    def create_exam(db: Session, exam_data: ExamCreate, teacher_id: UUID) -> Exam:
        """Create a new exam with questions."""
        exam = Exam(
            teacher_id=teacher_id,
            class_id=exam_data.class_id,
            title=exam_data.title,
            description=exam_data.description,
            duration_minutes=exam_data.duration_minutes,
            start_date=exam_data.start_date,
            end_date=exam_data.end_date,
            allow_retake=exam_data.allow_retake,
            max_attempts=exam_data.max_attempts
        )
        db.add(exam)
        db.flush()
        
        # Create questions
        for question_data in exam_data.questions:
            question = Question(
                exam_id=exam.id,
                question_text=question_data.question_text,
                question_type=question_data.question_type.value,
                difficulty_level=question_data.difficulty_level.value if question_data.difficulty_level else None,
                points=question_data.points,
                order_number=question_data.order_number
            )
            db.add(question)
            db.flush()
            
            # Create options for MCQ
            if question_data.options:
                for option_data in question_data.options:
                    option = QuestionOption(
                        question_id=question.id,
                        option_text=option_data.option_text,
                        is_correct=option_data.is_correct,
                        order_number=option_data.order_number
                    )
                    db.add(option)
        
        # Create default permission
        permission = ExamPermission(exam_id=exam.id)
        db.add(permission)
        
        db.commit()
        db.refresh(exam)
        return exam
    
    @staticmethod
    def get_exam(db: Session, exam_id: UUID) -> Exam:
        """Get exam by ID."""
        exam = db.query(Exam).filter(Exam.id == exam_id).first()
        if not exam:
            raise NotFoundError("Exam not found")
        return exam
    
    @staticmethod
    def get_exams(
        db: Session,
        teacher_id: Optional[UUID] = None,
        class_id: Optional[UUID] = None,
        is_published: Optional[bool] = None
    ) -> List[Exam]:
        """Get exams with filters."""
        query = db.query(Exam)
        
        if teacher_id:
            query = query.filter(Exam.teacher_id == teacher_id)
        if class_id:
            query = query.filter(Exam.class_id == class_id)
        if is_published is not None:
            query = query.filter(Exam.is_published == is_published)
        
        return query.all()
    
    @staticmethod
    def update_exam(db: Session, exam_id: UUID, exam_data: ExamUpdate) -> Exam:
        """Update exam."""
        exam = ExamService.get_exam(db, exam_id)
        
        if exam_data.title:
            exam.title = exam_data.title
        if exam_data.description is not None:
            exam.description = exam_data.description
        if exam_data.duration_minutes:
            exam.duration_minutes = exam_data.duration_minutes
        if exam_data.start_date is not None:
            exam.start_date = exam_data.start_date
        if exam_data.end_date is not None:
            exam.end_date = exam_data.end_date
        if exam_data.allow_retake is not None:
            exam.allow_retake = exam_data.allow_retake
        if exam_data.max_attempts is not None:
            exam.max_attempts = exam_data.max_attempts
        
        db.commit()
        db.refresh(exam)
        return exam
    
    @staticmethod
    def publish_exam(db: Session, exam_id: UUID, is_published: bool) -> Exam:
        """Publish/unpublish exam."""
        exam = ExamService.get_exam(db, exam_id)
        exam.is_published = is_published
        db.commit()
        db.refresh(exam)
        return exam
    
    @staticmethod
    def assign_exam_to_sections(db: Session, exam_id: UUID, section_ids: List[UUID]):
        """Assign exam to specific sections."""
        # Delete existing assignments
        db.query(ExamSection).filter(ExamSection.exam_id == exam_id).delete()
        
        # Create new assignments
        for section_id in section_ids:
            assignment = ExamSection(exam_id=exam_id, section_id=section_id)
            db.add(assignment)
        
        db.commit()

