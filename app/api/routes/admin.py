from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional, List
from app.database import get_db
from app.api.deps import get_admin_user, require_role
from app.models.user import User
from app.models.class_model import Class, Section
from app.services.user_service import UserService
from app.services.class_service import ClassService
from app.services.student_service import StudentService
from app.schemas.user import UserCreate, UserUpdate, UserResponse, BulkUserCreate
from app.schemas.class_schema import ClassCreate, ClassUpdate, ClassResponse, SectionCreate, SectionUpdate, SectionResponse
from app.schemas.student import (
    StudentRegistrationCreate, 
    StudentDetailResponse, 
    StudentUpdate, 
    StudentProfileResponse,
    StudentEnrollmentResponse
)
from app.schemas.common import PaginatedResponse, MessageResponse, DashboardStats
from app.utils.constants import UserRole

router = APIRouter()


@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all users with pagination."""
    role_enum = UserRole(role) if role else None
    result = UserService.get_users(db, page, limit, role_enum, search)
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get user details."""
    user = UserService.get_user(db, user_id)
    return UserResponse.model_validate(user)


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Create new user."""
    user = UserService.create_user(db, user_data)
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Update user."""
    user = UserService.update_user(db, user_id, user_data)
    return UserResponse.model_validate(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Delete user (soft delete)."""
    UserService.delete_user(db, user_id)
    return MessageResponse(message="User deleted")


@router.post("/users/bulk", response_model=dict)
async def bulk_create_users(
    users_data: BulkUserCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Bulk create users."""
    result = UserService.bulk_create_users(db, users_data.users)
    return result


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get admin dashboard statistics."""
    total_users = db.query(User).count()
    total_teachers = db.query(User).filter(User.role == UserRole.TEACHER.value).count()
    total_students = db.query(User).filter(User.role == UserRole.STUDENT.value).count()
    total_classes = db.query(Class).count()
    
    return DashboardStats(
        total_users=total_users,
        total_teachers=total_teachers,
        total_students=total_students,
        total_classes=total_classes,
        total_exams=0  # TODO: Add Exam model count
    )


# Classes endpoints
@router.get("/classes", response_model=List[ClassResponse])
async def list_classes(
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all classes."""
    classes = ClassService.get_all_classes(db)
    return [ClassResponse.model_validate(c) for c in classes]


@router.get("/classes/{class_id}", response_model=ClassResponse)
async def get_class(
    class_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get class details."""
    class_ = ClassService.get_class(db, class_id)
    return ClassResponse.model_validate(class_)


@router.post("/classes", response_model=ClassResponse)
async def create_class(
    class_data: ClassCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Create a new class."""
    class_ = ClassService.create_class(db, class_data, current_user.id)
    return ClassResponse.model_validate(class_)


@router.put("/classes/{class_id}", response_model=ClassResponse)
async def update_class(
    class_id: UUID,
    class_data: ClassUpdate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Update a class."""
    class_ = ClassService.update_class(db, class_id, class_data)
    return ClassResponse.model_validate(class_)


@router.delete("/classes/{class_id}", response_model=MessageResponse)
async def delete_class(
    class_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a class."""
    ClassService.delete_class(db, class_id)
    return MessageResponse(message="Class deleted successfully")


# Sections endpoints
@router.get("/sections", response_model=List[SectionResponse])
async def list_sections(
    class_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all sections, optionally filtered by class."""
    if class_id:
        sections = ClassService.get_sections(db, class_id)
    else:
        sections = db.query(Section).all()
    return [SectionResponse.model_validate(s) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionResponse)
async def get_section(
    section_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get section details."""
    section = db.query(Section).filter(Section.id == section_id).first()
    if not section:
        from app.middleware.error_handler import NotFoundError
        raise NotFoundError("Section not found")
    return SectionResponse.model_validate(section)


@router.post("/classes/{class_id}/sections", response_model=SectionResponse)
async def create_section(
    class_id: UUID,
    section_data: SectionCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Create a new section in a class."""
    section = ClassService.create_section(db, class_id, section_data)
    return SectionResponse.model_validate(section)


@router.put("/sections/{section_id}", response_model=SectionResponse)
async def update_section(
    section_id: UUID,
    section_data: SectionUpdate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Update a section."""
    section = ClassService.update_section(db, section_id, section_data)
    return SectionResponse.model_validate(section)


@router.delete("/sections/{section_id}", response_model=MessageResponse)
async def delete_section(
    section_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Delete a section."""
    ClassService.delete_section(db, section_id)
    return MessageResponse(message="Section deleted successfully")


# Teacher-Class Assignment endpoints
@router.post("/classes/{class_id}/teachers/{teacher_id}", response_model=MessageResponse)
async def assign_teacher_to_class(
    class_id: UUID,
    teacher_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Assign a teacher to a class."""
    # Verify class exists
    class_ = ClassService.get_class(db, class_id)
    
    # Verify user is a teacher
    teacher = db.query(User).filter(User.id == teacher_id, User.role == 'teacher').first()
    if not teacher:
        from app.middleware.error_handler import ValidationError
        raise ValidationError("User is not a teacher")
    
    # Assign teacher to class
    ClassService.assign_teacher_to_class(db, teacher_id, class_id)
    return MessageResponse(message=f"Teacher assigned to class '{class_.name}' successfully")


@router.delete("/classes/{class_id}/teachers/{teacher_id}", response_model=MessageResponse)
async def remove_teacher_from_class(
    class_id: UUID,
    teacher_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Remove a teacher from a class."""
    from app.models.class_model import TeacherClass
    
    # Verify assignment exists
    assignment = db.query(TeacherClass).filter(
        TeacherClass.teacher_id == teacher_id,
        TeacherClass.class_id == class_id
    ).first()
    
    if not assignment:
        from app.middleware.error_handler import NotFoundError
        raise NotFoundError("Teacher is not assigned to this class")
    
    db.delete(assignment)
    db.commit()
    
    return MessageResponse(message="Teacher removed from class successfully")


# Student Registration endpoints
@router.post("/students", response_model=UserResponse)
async def register_student(
    student_data: StudentRegistrationCreate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Register a new student with complete profile information."""
    student = StudentService.create_student_with_profile(db, student_data, current_user.id)
    return UserResponse.model_validate(student)


@router.get("/students", response_model=PaginatedResponse[UserResponse])
async def list_students(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    class_id: Optional[UUID] = Query(None),
    section_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """List all students with pagination and filters."""
    result = StudentService.get_all_students(db, page, limit, search, class_id, section_id)
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.get("/students/{student_id}", response_model=StudentDetailResponse)
async def get_student(
    student_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get student details with profile and enrollment information."""
    from app.models.student_profile import StudentProfile
    from app.models.class_model import StudentClass
    
    user = StudentService.get_student_by_id(db, student_id)
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    enrollments = db.query(StudentClass).filter(StudentClass.student_id == user.id).all()
    
    return StudentDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        email_verified=user.email_verified,
        is_active=user.is_active,
        created_at=user.created_at,
        profile=StudentProfileResponse.model_validate(profile) if profile else None,
        enrollments=[StudentEnrollmentResponse.model_validate(e) for e in enrollments]
    )


@router.put("/students/{student_id}/profile", response_model=StudentProfileResponse)
async def update_student_profile(
    student_id: UUID,
    profile_data: StudentUpdate,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Update student profile information."""
    profile = StudentService.update_student_profile(db, student_id, profile_data)
    return StudentProfileResponse.model_validate(profile)


@router.put("/students/{student_id}/password")
async def change_student_password(
    student_id: UUID,
    password_data: dict,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Change student password with current password verification."""
    current_password = password_data.get('current_password')
    new_password = password_data.get('new_password')
    
    if not current_password or not new_password:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Both current_password and new_password are required")
    
    StudentService.change_student_password(db, student_id, current_password, new_password)
    return {"message": "Password changed successfully"}


@router.get("/classes/{class_id}/sections/{section_id}/students", response_model=List[UserResponse])
async def get_students_by_class_section(
    class_id: UUID,
    section_id: UUID,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all students in a specific class and section."""
    students = StudentService.get_students_by_class_section(db, class_id, section_id)
    return [UserResponse.model_validate(s) for s in students]

