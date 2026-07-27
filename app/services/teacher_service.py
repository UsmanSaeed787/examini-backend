from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from app.models.user import User
from app.models.class_model import Class, TeacherClass, StudentClass
from app.models.exam import Exam
from app.models.material import Material
from app.utils.helpers import paginate_response
from app.utils.constants import UserRole


class TeacherService:
    """Service for teacher-specific operations."""

    @staticmethod
    def verify_teacher_class_access(db: Session, teacher_id: UUID, class_id: UUID) -> bool:
        """Verify that teacher has access to the class."""
        access = db.query(TeacherClass).filter(
            TeacherClass.teacher_id == teacher_id,
            TeacherClass.class_id == class_id
        ).first()
        return access is not None

    @staticmethod
    def get_teacher_classes(db: Session, teacher_id: UUID) -> List[Class]:
        """
        Get all classes from the classes table that admin created.
        
        Returns ALL classes from the classes table (created by admin),
        not filtered by teacher assignment. Teachers can see all admin-created classes,
        but access is validated when uploading materials or creating exams.
        """
        # Get ALL classes from the classes table (admin-created)
        classes = db.query(Class).order_by(Class.name).all()
        return classes

    @staticmethod
    def get_teacher_students(
        db: Session,
        teacher_id: UUID,
        class_id: Optional[UUID] = None,
        section_id: Optional[UUID] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 10
    ) -> dict:
        """
        Get ALL students from users table (role='student').
        
        Returns ALL students from the users table where role='student',
        same way admin gets users. Teachers can see all students, but can filter
        by class_id and section_id if needed.
        """
        # Use StudentService.get_all_students to get all students (same as admin)
        from app.services.student_service import StudentService
        return StudentService.get_all_students(db, page, limit, search, class_id, section_id)

    @staticmethod
    def get_dashboard_stats(db: Session, teacher_id: UUID) -> dict:
        """Get teacher dashboard statistics."""
        # Get ALL classes count (from admin-created classes table)
        total_classes = db.query(func.count(Class.id)).scalar() or 0

        # Get ALL students count from users table (role='student')
        # Same way admin gets users - teachers can see all students
        total_students = db.query(func.count(User.id)).filter(
            and_(
                User.role == UserRole.STUDENT.value,
                User.is_active == True
            )
        ).scalar() or 0

        # Get exams count created by this teacher
        total_exams = db.query(func.count(Exam.id)).filter(
            Exam.teacher_id == teacher_id
        ).scalar() or 0

        # Get recent exams (last 5) created by this teacher
        recent_exams = db.query(Exam).filter(
            Exam.teacher_id == teacher_id
        ).order_by(Exam.created_at.desc()).limit(5).all()

        # Get materials count uploaded by this teacher
        # Count all materials (don't filter by is_active - count everything)
        total_materials = db.query(func.count(Material.id)).filter(
            Material.teacher_id == teacher_id
        ).scalar() or 0

        return {
            "total_classes": total_classes,
            "total_students": total_students,
            "total_exams": total_exams,
            "total_materials": total_materials,
            "recent_exams": [
                {
                    "id": str(exam.id),
                    "title": exam.title,
                    "is_published": exam.is_published,
                    "created_at": exam.created_at.isoformat() if exam.created_at else None
                }
                for exam in recent_exams
            ]
        }

