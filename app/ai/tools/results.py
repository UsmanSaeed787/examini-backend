"""Result tools — read-only queries over exam_results/exam_responses.

`results.pending_text_answers` is the grader agent's data source: the
short/long answers the platform stores as is_correct=NULL — the agent
PROPOSES scores in conversation; persisting a review remains a service-layer
extension (exam_results.reviewed_by seam)."""
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolContext, tool
from app.middleware.error_handler import AuthorizationError
from app.models.attempt import ExamAttempt, ExamResponse, ExamResult
from app.models.exam import Exam, Question
from app.services.exam_service import ExamService


class ExamIdParams(BaseModel):
    exam_id: str = Field(description="Exam id (UUID)")


@tool(
    key="results.list_for_exam",
    description="List all graded results for one of the calling teacher's exams.",
    params=ExamIdParams,
    services=("ExamService",),
    tags=("results", "read"),
)
def list_exam_results(ctx: ToolContext, params: ExamIdParams) -> list[dict]:
    with ctx.db() as db:
        exam = ExamService.get_exam(db, UUID(params.exam_id))
        if ctx.identity.role == "teacher" and exam.teacher_id != ctx.identity.user_id:
            raise AuthorizationError("You do not have access to this exam")
        rows = (
            db.query(ExamResult, ExamAttempt)
            .join(ExamAttempt, ExamResult.attempt_id == ExamAttempt.id)
            .filter(ExamAttempt.exam_id == exam.id)
            .all()
        )
        return [
            {
                "attempt_id": str(attempt.id),
                "student_id": str(attempt.student_id),
                "total_score": float(result.total_score),
                "max_score": float(result.max_score),
                "percentage": float(result.percentage),
                "grade": result.grade,
                "passed": bool(result.passed),
                "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            }
            for result, attempt in rows
        ]


@tool(
    key="results.pending_text_answers",
    description="List ungraded short/long text answers for one of the calling teacher's exams.",
    params=ExamIdParams,
    services=("ExamService",),
    tags=("results", "grading", "read"),
)
def get_pending_text_answers(ctx: ToolContext, params: ExamIdParams) -> list[dict]:
    with ctx.db() as db:
        exam = ExamService.get_exam(db, UUID(params.exam_id))
        if exam.teacher_id != ctx.identity.user_id:
            raise AuthorizationError("You do not have access to this exam")
        rows = (
            db.query(ExamResponse, Question, ExamAttempt)
            .join(Question, ExamResponse.question_id == Question.id)
            .join(ExamAttempt, ExamResponse.attempt_id == ExamAttempt.id)
            .filter(
                ExamAttempt.exam_id == exam.id,
                Question.question_type.in_(["short_answer", "long_answer"]),
                ExamResponse.is_correct.is_(None),
            )
            .all()
        )
        return [
            {
                "response_id": str(response.id),
                "attempt_id": str(attempt.id),
                "question_text": question.question_text,
                "question_points": float(question.points or 0),
                "answer_text": response.answer_text,
            }
            for response, question, attempt in rows
        ]


@tool(
    key="results.my_results",
    description="List the calling student's own exam results.",
    services=(),
    tags=("results", "read", "self"),
)
def get_my_results(ctx: ToolContext, params=None) -> list[dict]:
    with ctx.db() as db:
        rows = (
            db.query(ExamResult, ExamAttempt, Exam)
            .join(ExamAttempt, ExamResult.attempt_id == ExamAttempt.id)
            .join(Exam, ExamAttempt.exam_id == Exam.id)
            .filter(ExamAttempt.student_id == ctx.identity.user_id)
            .all()
        )
        return [
            {
                "exam_title": exam.title,
                "total_score": float(result.total_score),
                "max_score": float(result.max_score),
                "percentage": float(result.percentage),
                "grade": result.grade,
                "passed": bool(result.passed),
                "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            }
            for result, attempt, exam in rows
        ]
