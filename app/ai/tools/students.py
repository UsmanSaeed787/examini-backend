"""Student self-scoped tools — enrollment and upcoming exams (read-only)."""
from datetime import datetime, timezone

from app.ai.tools.registry import ToolContext, tool
from app.models.class_model import Class, Section, StudentClass
from app.models.exam import Exam


@tool(
    key="students.my_enrollments",
    description="List the calling student's class/section enrollments and roll numbers.",
    services=(),
    tags=("students", "read", "self"),
)
def get_my_enrollments(ctx: ToolContext, params=None) -> list[dict]:
    with ctx.db() as db:
        rows = (
            db.query(StudentClass, Class, Section)
            .join(Class, StudentClass.class_id == Class.id)
            .join(Section, StudentClass.section_id == Section.id)
            .filter(StudentClass.student_id == ctx.identity.user_id)
            .all()
        )
        return [
            {
                "class_id": str(cls.id),
                "class_name": cls.name,
                "section_name": section.name,
                "roll_number": enrollment.roll_number,
            }
            for enrollment, cls, section in rows
        ]


@tool(
    key="students.my_upcoming_exams",
    description="List published exams (not yet ended) in the calling student's enrolled classes.",
    services=(),
    tags=("students", "exams", "read", "self"),
)
def get_my_upcoming_exams(ctx: ToolContext, params=None) -> list[dict]:
    with ctx.db() as db:
        class_ids = [
            row.class_id
            for row in db.query(StudentClass)
            .filter(StudentClass.student_id == ctx.identity.user_id)
            .all()
        ]
        if not class_ids:
            return []
        now = datetime.now(timezone.utc)
        exams = (
            db.query(Exam)
            .filter(
                Exam.class_id.in_(class_ids),
                Exam.is_published == True,  # noqa: E712
                Exam.end_date >= now,
            )
            .order_by(Exam.start_date.asc())
            .limit(20)
            .all()
        )
        return [
            {
                "id": str(e.id),
                "title": e.title,
                "duration_minutes": e.duration_minutes,
                "start_date": e.start_date.isoformat() if e.start_date else None,
                "end_date": e.end_date.isoformat() if e.end_date else None,
            }
            for e in exams
        ]
