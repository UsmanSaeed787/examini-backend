from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from typing import Optional, List
import os
import re
import traceback
from pathlib import Path

from app.database import get_db
from app.api.deps import get_teacher_user
from app.models.user import User
from app.middleware.error_handler import AuthorizationError
from app.schemas.common import MessageResponse, DashboardStats, PaginatedResponse
from app.schemas.user import UserResponse
from app.schemas.material import MaterialCreate, MaterialUpdate, MaterialResponse
from app.schemas.exam import ExamCreate, ExamUpdate, ExamResponse, ExamGenerate, ExamDetailResponse
from app.schemas.class_schema import ClassResponse
from app.schemas.student import (
    StudentRegistrationCreate,
    StudentUpdate,
    StudentDetailResponse,
    StudentProfileResponse,
    StudentEnrollmentResponse
)
from app.services.teacher_service import TeacherService
from app.services.material_service import MaterialService
from app.services.exam_service import ExamService
from app.services.openai_service import OpenAIService
from app.services.storage_service import StorageService
from app.config import settings
from app.utils.constants import QuestionType, DifficultyLevel, UserRole
from app.models.attempt import ExamAttempt, ExamResult
from app.models.exam import Exam
from app.models.user import User
from sqlalchemy import and_

router = APIRouter()


# Results Management
@router.get("/results", response_model=PaginatedResponse)
async def list_results(
    exam_id: Optional[UUID] = Query(None, description="Filter by exam ID"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """List exam results for exams created by the teacher - simple from exam_results table."""
    try:
        # Simple query: Get results from exam_results table for exams created by this teacher
        query = db.query(ExamResult).join(ExamAttempt).join(Exam).filter(
            Exam.teacher_id == current_user.id
        )
        
        if exam_id:
            query = query.filter(Exam.id == exam_id)
        
        total = query.count()
        results = query.order_by(ExamResult.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        
        # Simple result list from exam_results table
        result_list = []
        for result in results:
            attempt = db.query(ExamAttempt).filter(ExamAttempt.id == result.attempt_id).first()
            if not attempt:
                continue
                
            exam = db.query(Exam).filter(Exam.id == attempt.exam_id).first()
            if not exam:
                continue
                
            student = db.query(User).filter(User.id == attempt.student_id).first()
            if not student:
                continue
            
            result_list.append({
                "id": str(result.id),
                "exam_id": str(exam.id),
                "exam_name": exam.title,
                "student_id": str(student.id),
                "student_name": student.full_name or student.email,
                "student_email": student.email,
                "total_score": float(result.total_score),
                "max_score": float(result.max_score),
                "percentage": float(result.percentage),
                "grade": result.grade,
                "passed": result.passed,
                "created_at": result.created_at.isoformat() if result.created_at else None,
            })
        
        return PaginatedResponse(
            items=result_list,
            total=total,
            page=page,
            limit=limit,
            pages=(total + limit - 1) // limit
        )
    except Exception as e:
        print(f"Error fetching teacher results: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching results: {str(e)}")


# Dashboard
@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Get teacher dashboard data."""
    stats = TeacherService.get_dashboard_stats(db, current_user.id)
    return DashboardStats(**stats)


# Student Management
@router.get("/students", response_model=PaginatedResponse[UserResponse])
async def list_students(
    class_id: Optional[UUID] = Query(None, description="Filter by class ID"),
    section_id: Optional[UUID] = Query(None, description="Filter by section ID"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """
    List ALL students from users table (role='student').
    
    Returns ALL students from the users table where role='student',
    same way admin gets users. Teachers can see all students.
    """
    result = TeacherService.get_teacher_students(
        db, current_user.id, class_id, section_id, search, page, limit
    )
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.post("/students", response_model=UserResponse)
async def register_student(
    student_data: StudentRegistrationCreate,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Register a new student with complete profile information."""
    from app.services.student_service import StudentService
    student = StudentService.create_student_with_profile(db, student_data, current_user.id)
    return UserResponse.model_validate(student)


@router.get("/students/{student_id}", response_model=StudentDetailResponse)
async def get_student(
    student_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Get student details with profile and enrollment information."""
    from app.models.student_profile import StudentProfile
    from app.models.class_model import StudentClass
    from app.services.student_service import StudentService
    
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
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Update student profile information."""
    from app.services.student_service import StudentService
    profile = StudentService.update_student_profile(db, student_id, profile_data)
    return StudentProfileResponse.model_validate(profile)


@router.delete("/students/{student_id}", response_model=MessageResponse)
async def delete_student(
    student_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Delete a student (soft delete)."""
    from app.services.user_service import UserService
    # Verify it's a student
    user = UserService.get_user(db, student_id)
    if user.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=403, detail="Can only delete students")
    UserService.delete_user(db, student_id)
    return MessageResponse(message="Student deleted successfully")


@router.get("/classes", response_model=List[ClassResponse])
async def get_teacher_classes(
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """
    Get all classes from the classes table (admin-created).
    
    Returns ALL classes from the classes table that were created by admin.
    Teachers can view all classes, but access validation occurs when uploading
    materials or creating exams to ensure the class is assigned to the teacher.
    """
    try:
        from app.services.class_service import ClassService
        classes = ClassService.get_all_classes(db)
        return [ClassResponse.model_validate(cls) for cls in classes]
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching classes: {str(e)}")


# Material Management
@router.get("/materials", response_model=PaginatedResponse[MaterialResponse])
async def list_materials(
    class_id: Optional[UUID] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """List materials uploaded by the teacher."""
    result = MaterialService.get_materials(
        db, current_user.id, class_id, page, limit, search
    )
    return PaginatedResponse(
        items=[MaterialResponse.model_validate(m) for m in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"]
    )


@router.post("/materials", response_model=MaterialResponse)
async def upload_material(
    file: UploadFile = File(...),
    title: str = Form(...),
    class_id: UUID = Form(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """
    Upload a new material.
    
    Teachers can upload materials to any admin-created class from the classes table.
    No assignment is required - teachers have access to all admin-created classes.
    """
    try:
        # Validate file type
        if not file.filename:
            raise HTTPException(status_code=400, detail="File name is required")
        
        file_ext = Path(file.filename).suffix.lower().lstrip('.')
        if not file_ext or file_ext not in settings.allowed_file_types_list:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(settings.allowed_file_types_list)}"
            )
        
        # Validate file size
        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)
        if file_size_mb > settings.max_file_size_mb:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds maximum allowed size of {settings.max_file_size_mb}MB"
            )
        
        # Upload to Cloudinary (unique public id, sanitized original filename)
        safe_filename = re.sub(r'[^a-zA-Z0-9._-]', '_', file.filename or 'file')
        file_id = str(uuid4())  # Generate random UUID
        try:
            file_url = StorageService.upload_file(content, f"{file_id}_{safe_filename}")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file to storage: {str(e)}" if settings.debug else "Failed to upload file to storage"
            )
        
        # Create material
        material_data = MaterialCreate(
            title=title,
            description=description,
            class_id=class_id
        )
        
        try:
            material = MaterialService.create_material(
                db,
                material_data,
                current_user.id,
                file_url=file_url,  # Cloudinary https URL
                file_name=file.filename,
                file_type=file_ext,
                file_size=len(content)
            )
        except Exception as e:
            # DB save failed; the orphaned Cloudinary file is harmless
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create material record: {str(e)}"
            )
        
        return MaterialResponse.model_validate(material)
    
    except HTTPException:
        raise
    except Exception as e:
        error_details = traceback.format_exc()
        if settings.debug:
            print(f"Material upload error: {error_details}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}" if settings.debug else "Failed to upload material"
        )


@router.get("/materials/{material_id}", response_model=MaterialResponse)
async def get_material(
    material_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Get material details."""
    material = MaterialService.get_material(db, material_id, current_user.id)
    return MaterialResponse.model_validate(material)


@router.get("/materials/{material_id}/download")
async def download_material(
    material_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Download a material file."""
    material = MaterialService.get_material(db, material_id, current_user.id)

    # Cloudinary-hosted file: proxy the bytes so auth stays enforced
    if material.file_url.startswith("http"):
        try:
            file_bytes = StorageService.fetch_file(material.file_url)
        except Exception:
            raise HTTPException(status_code=404, detail="File not found in storage")
        return Response(
            content=file_bytes,
            media_type='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{material.file_name}"'}
        )

    # Legacy local file (pre-Cloudinary uploads)
    file_path = Path(material.file_url)
    if not file_path.is_absolute():
        # If relative, resolve from backend root
        backend_root = Path(__file__).parent.parent.parent
        file_path = backend_root / file_path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        str(file_path),
        filename=material.file_name,
        media_type='application/octet-stream'
    )


@router.put("/materials/{material_id}", response_model=MaterialResponse)
async def update_material(
    material_id: UUID,
    material_data: MaterialUpdate,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Update material metadata."""
    material = MaterialService.update_material(db, material_id, material_data, current_user.id)
    return MaterialResponse.model_validate(material)


@router.delete("/materials/{material_id}", response_model=MessageResponse)
async def delete_material(
    material_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Delete a material."""
    MaterialService.delete_material(db, material_id, current_user.id)
    return MessageResponse(message="Material deleted successfully")


# Exam Management
@router.get("/exams", response_model=PaginatedResponse[ExamResponse])
async def list_exams(
    class_id: Optional[UUID] = Query(None),
    is_published: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """List exams created by the teacher."""
    exams = ExamService.get_exams(
        db, teacher_id=current_user.id, class_id=class_id, is_published=is_published
    )
    
    # Manual pagination
    total = len(exams)
    start = (page - 1) * limit
    end = start + limit
    paginated_exams = exams[start:end]
    
    return PaginatedResponse(
        items=[ExamResponse.model_validate(e) for e in paginated_exams],
        total=total,
        page=page,
        limit=limit,
        pages=(total + limit - 1) // limit
    )


@router.get("/exams/{exam_id}", response_model=ExamDetailResponse)
async def get_exam(
    exam_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Get exam details with questions."""
    exam = ExamService.get_exam(db, exam_id)
    
    # Verify ownership
    if exam.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this exam")
    
    # Load questions with options
    from app.models.exam import Question, QuestionOption
    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    question_responses = []
    
    for question in questions:
        options = None
        if question.question_type == QuestionType.MCQ.value or question.question_type == QuestionType.TRUE_FALSE.value:
            options = db.query(QuestionOption).filter(QuestionOption.question_id == question.id).all()
            options = [
                {
                    "id": str(opt.id),
                    "option_text": opt.option_text,
                    "is_correct": opt.is_correct,
                    "order_number": opt.order_number
                }
                for opt in options
            ]
        
        question_responses.append({
            "id": str(question.id),
            "question_text": question.question_text,
            "question_type": question.question_type,
            "difficulty_level": question.difficulty_level,
            "points": float(question.points),
            "order_number": question.order_number,
            "options": options
        })
    
    exam_dict = ExamResponse.model_validate(exam).model_dump()
    exam_dict["questions"] = question_responses
    
    return ExamDetailResponse(**exam_dict)


@router.post("/exams", response_model=ExamResponse)
async def create_exam(
    exam_data: ExamCreate,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """
    Create a new exam.
    
    Teachers can create exams for any admin-created class from the classes table.
    No assignment is required - teachers have access to all admin-created classes.
    """
    # Verify class exists
    from app.models.class_model import Class
    class_ = db.query(Class).filter(Class.id == exam_data.class_id).first()
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")
    
    exam = ExamService.create_exam(db, exam_data, current_user.id)
    return ExamResponse.model_validate(exam)


@router.post("/exams/generate", response_model=ExamResponse)
async def generate_exam(
    exam_data: ExamGenerate,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """
    Generate an exam using OpenAI from uploaded materials.
    
    Teachers can generate exams for any admin-created class from the classes table.
    No assignment is required - teachers have access to all admin-created classes.
    Materials must belong to the teacher.
    """
    # Verify class exists
    from app.models.class_model import Class
    class_ = db.query(Class).filter(Class.id == exam_data.class_id).first()
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")

    # AI Operating Layer strangler branch (AI_LAYER_DESIGN.md Phase 1):
    # flag on -> guardrailed agent run via the facade; flag off -> the
    # legacy OpenAIService path below, byte-for-byte.
    from app.ai.config import ai_settings
    if ai_settings.enabled and ai_settings.use_agents_for_generation:
        from app.ai import facade
        exam = await facade.generate_exam(current_user, exam_data)
        return ExamResponse.model_validate(exam)

    # Get materials
    materials = MaterialService.get_materials_by_ids(db, exam_data.material_ids, current_user.id)
    if len(materials) != len(exam_data.material_ids):
        raise HTTPException(status_code=400, detail="Some materials not found or not accessible")
    
    # Extract real text from each material (pdf/docx/txt)
    try:
        material_texts = [OpenAIService.parse_material_file(m) for m in materials]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Generate questions
    openai_service = OpenAIService()
    try:
        questions_data = await openai_service.generate_exam_from_materials(
            material_texts, exam_data.question_config
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate exam: {str(e)}")
    
    # Convert to QuestionCreate format
    from app.schemas.exam import QuestionCreate, QuestionOptionCreate
    
    questions = []
    for idx, q_data in enumerate(questions_data, 1):
        options = None
        if q_data.get("question_type") in ["mcq", "true_false"] and q_data.get("options"):
            options = [
                QuestionOptionCreate(
                    option_text=opt["option_text"],
                    is_correct=opt.get("is_correct", False),
                    order_number=opt.get("order_number", i + 1)
                )
                for i, opt in enumerate(q_data["options"])
            ]
        
        questions.append(QuestionCreate(
            question_text=q_data["question_text"],
            question_type=QuestionType(q_data["question_type"]),
            difficulty_level=DifficultyLevel(q_data.get("difficulty_level", "medium")),
            points=float(q_data.get("points", 1.0)),
            order_number=q_data.get("order_number", idx),
            options=options
        ))
    
    # Create exam
    exam_create = ExamCreate(
        title=exam_data.title,
        description=exam_data.description,
        class_id=exam_data.class_id,
        duration_minutes=exam_data.duration_minutes,
        start_date=exam_data.start_date,
        end_date=exam_data.end_date,
        allow_retake=exam_data.allow_retake,
        max_attempts=exam_data.max_attempts,
        questions=questions
    )
    
    exam = ExamService.create_exam(db, exam_create, current_user.id)
    return ExamResponse.model_validate(exam)


@router.put("/exams/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: UUID,
    exam_data: ExamUpdate,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Update exam details."""
    exam = ExamService.get_exam(db, exam_id)
    
    # Verify ownership
    if exam.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this exam")
    
    exam = ExamService.update_exam(db, exam_id, exam_data)
    return ExamResponse.model_validate(exam)


@router.post("/exams/{exam_id}/publish", response_model=ExamResponse)
async def publish_exam(
    exam_id: UUID,
    is_published: bool = Form(...),
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Publish or unpublish an exam."""
    exam = ExamService.get_exam(db, exam_id)
    
    # Verify ownership
    if exam.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this exam")
    
    exam = ExamService.publish_exam(db, exam_id, is_published)
    return ExamResponse.model_validate(exam)


@router.delete("/exams/{exam_id}", response_model=MessageResponse)
async def delete_exam(
    exam_id: UUID,
    current_user: User = Depends(get_teacher_user),
    db: Session = Depends(get_db)
):
    """Delete an exam."""
    exam = ExamService.get_exam(db, exam_id)
    
    # Verify ownership
    if exam.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this exam")
    
    db.delete(exam)
    db.commit()
    return MessageResponse(message="Exam deleted successfully")
