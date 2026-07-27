from sqlalchemy.orm import Session
from uuid import UUID
from decimal import Decimal
from app.models.attempt import ExamAttempt, ExamResponse, ExamResult
from app.models.exam import Question, QuestionOption
from app.utils.helpers import calculate_grade
from app.middleware.error_handler import NotFoundError


class ResultService:
    """Service for exam result calculation."""
    
    @staticmethod
    def calculate_result(db: Session, attempt_id: UUID) -> ExamResult:
        """Calculate exam result for a submitted attempt."""
        attempt = db.query(ExamAttempt).filter(ExamAttempt.id == attempt_id).first()
        if not attempt:
            raise NotFoundError("Exam attempt not found")
        
        if attempt.status != "submitted":
            raise ValueError("Attempt must be submitted to calculate result")
        
        # Get all responses
        responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt_id).all()
        
        # Calculate scores
        total_score = Decimal(0)
        max_score = Decimal(0)
        
        for response in responses:
            question = db.query(Question).filter(Question.id == response.question_id).first()
            if question:
                max_score += Decimal(str(question.points))
                if response.is_correct:
                    total_score += Decimal(str(response.points_earned))
        
        # Calculate percentage
        if max_score > 0:
            percentage = (total_score / max_score) * 100
        else:
            percentage = Decimal(0)
        
        # Determine grade
        grade, passed = calculate_grade(float(percentage))
        
        # Create or update result
        result = db.query(ExamResult).filter(ExamResult.attempt_id == attempt_id).first()
        if result:
            result.total_score = total_score
            result.max_score = max_score
            result.percentage = percentage
            result.grade = grade
            result.passed = passed
        else:
            result = ExamResult(
                attempt_id=attempt_id,
                total_score=total_score,
                max_score=max_score,
                percentage=percentage,
                grade=grade,
                passed=passed
            )
            db.add(result)
        
        db.commit()
        db.refresh(result)
        return result
    
    @staticmethod
    def auto_grade_mcq(db: Session, attempt_id: UUID):
        """Auto-grade MCQ and True/False questions."""
        responses = db.query(ExamResponse).filter(ExamResponse.attempt_id == attempt_id).all()
        
        for response in responses:
            question = db.query(Question).filter(Question.id == response.question_id).first()
            if not question or question.question_type not in ["mcq", "true_false"]:
                continue
            
            # Get correct options
            correct_options = db.query(QuestionOption).filter(
                QuestionOption.question_id == question.id,
                QuestionOption.is_correct == True
            ).all()
            correct_option_ids = [str(opt.id) for opt in correct_options]
            
            # Check if selected options match
            selected = [str(opt) for opt in (response.selected_options or [])]
            is_correct = set(selected) == set(correct_option_ids) and len(selected) == len(correct_option_ids)
            
            response.is_correct = is_correct
            response.points_earned = Decimal(str(question.points)) if is_correct else Decimal(0)
        
        db.commit()

