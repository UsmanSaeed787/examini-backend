"""Exam tools — wrap ExamService (teacher-scoped, read-only for agents;
persistence of generated exams happens deterministically in the facade)."""
from collections import Counter
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolContext, tool
from app.middleware.error_handler import AuthorizationError
from app.services.exam_service import ExamService


class GetExamOverviewParams(BaseModel):
    exam_id: str = Field(description="Exam id (UUID)")


@tool(
    key="exams.list_own",
    description="List the calling teacher's exams (id, title, published state, duration).",
    services=("ExamService",),
    tags=("exams", "read"),
)
def list_own_exams(ctx: ToolContext, params=None) -> list[dict]:
    with ctx.db() as db:
        exams = ExamService.get_exams(db, teacher_id=ctx.identity.user_id)
        return [
            {
                "id": str(e.id),
                "title": e.title,
                "class_id": str(e.class_id),
                "is_published": bool(e.is_published),
                "duration_minutes": e.duration_minutes,
            }
            for e in exams
        ]


@tool(
    key="exams.get_overview",
    description="Get a structural overview of one of the calling teacher's exams "
    "(question counts by type and difficulty, total points).",
    params=GetExamOverviewParams,
    services=("ExamService",),
    tags=("exams", "read"),
)
def get_exam_overview(ctx: ToolContext, params: GetExamOverviewParams) -> dict:
    with ctx.db() as db:
        exam = ExamService.get_exam(db, UUID(params.exam_id))
        if exam.teacher_id != ctx.identity.user_id:
            raise AuthorizationError("You do not have access to this exam")
        types = Counter(q.question_type for q in exam.questions)
        difficulties = Counter(q.difficulty_level for q in exam.questions if q.difficulty_level)
        return {
            "id": str(exam.id),
            "title": exam.title,
            "is_published": bool(exam.is_published),
            "duration_minutes": exam.duration_minutes,
            "question_count": len(exam.questions),
            "question_types": dict(types),
            "difficulty_levels": dict(difficulties),
            "total_points": float(sum(q.points or 0 for q in exam.questions)),
        }
