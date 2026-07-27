from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from app.models.user import User
from app.models.class_model import Class, StudentClass
from app.models.exam import Exam
from app.models.attempt import ExamAttempt, ExamResult
from app.models.material import Material
from app.models.student_profile import StudentProfile
from app.schemas.student import StudentRegistrationCreate, StudentUpdate
from app.utils.constants import UserRole, ExamAttemptStatus
from app.middleware.error_handler import NotFoundError, ValidationError
from app.utils.security import get_password_hash, validate_password
from app.utils.helpers import paginate_response
import secrets
import string


def to_utc_z(dt: Optional[datetime]) -> Optional[str]:
    """Convert datetime to UTC ISO string with Z suffix.
    
    Always sends timezone-aware UTC timestamps with Z suffix.
    If datetime is naive, assumes it's already UTC and adds timezone info.
    """
    if not dt:
        return None
    
    # If naive (no timezone), assume UTC and add timezone info
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Convert to UTC timezone and format as ISO with Z suffix
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')


class StudentService:
    """Service for student-specific operations."""

    @staticmethod
    def get_student_classes(db: Session, student_id: UUID) -> List[UUID]:
        """Get list of class IDs the student is enrolled in."""
        enrollments = db.query(StudentClass.class_id).filter(
            StudentClass.student_id == student_id
        ).all()
        return [enrollment[0] for enrollment in enrollments]

    @staticmethod
    def get_dashboard_stats(db: Session, student_id: UUID) -> dict:
        """Get student dashboard statistics."""
        # Get student's enrolled class IDs
        class_ids = StudentService.get_student_classes(db, student_id)
        
        if not class_ids:
            return {
                "available_exams": 0,
                "completed_exams": 0,
                "total_materials": 0,
                "upcoming_exams": []
            }

        # Get available exams count: ALL published exams in student's classes
        # This includes both available (started) and upcoming (not yet started) exams
        now = datetime.now(timezone.utc)
        available_exams_count = db.query(func.count(Exam.id)).filter(
            and_(
                Exam.is_published == True,
                Exam.class_id.in_(class_ids),
                # Either no end date, or end date hasn't passed
                or_(
                    Exam.end_date.is_(None),
                    Exam.end_date >= now
                )
            )
        ).scalar() or 0

        # Get completed exams count (exams with submitted attempts)
        completed_exam_ids = db.query(ExamAttempt.exam_id).filter(
            and_(
                ExamAttempt.student_id == student_id,
                ExamAttempt.status == ExamAttemptStatus.SUBMITTED.value
            )
        ).distinct().all()
        completed_exams_count = len(completed_exam_ids)

        # Get materials count in student's classes
        total_materials_count = db.query(func.count(Material.id)).filter(
            and_(
                Material.class_id.in_(class_ids),
                Material.is_active == True
            )
        ).scalar() or 0

        # Get upcoming exams (published, not yet started, in student's classes)
        upcoming_exams = db.query(Exam).join(Class).filter(
            and_(
                Exam.is_published == True,
                Exam.class_id.in_(class_ids),
                Exam.start_date.isnot(None),
                Exam.start_date > now
            )
        ).order_by(Exam.start_date.asc()).limit(5).all()

        return {
            "available_exams": available_exams_count,
            "completed_exams": completed_exams_count,
            "total_materials": total_materials_count,
            "upcoming_exams": [
                {
                    "id": str(exam.id),
                    "title": exam.title,
                    "description": exam.description,
                    "class_name": exam.class_.name if exam.class_ else None,
                    "start_date": to_utc_z(exam.start_date) if exam.start_date else None,
                    "end_date": to_utc_z(exam.end_date) if exam.end_date else None,
                    "duration_minutes": exam.duration_minutes
                }
                for exam in upcoming_exams
            ]
        }

    @staticmethod
    def get_available_exams(
        db: Session,
        student_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 10
    ) -> dict:
        """Get exams available to student."""
        # Get student's enrolled class IDs
        class_ids = StudentService.get_student_classes(db, student_id)
        
        if not class_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "pages": 0
            }

        # Base query: published exams in student's classes
        now = datetime.now(timezone.utc)
        
        # Start with all published exams in student's classes
        base_query = db.query(Exam).filter(
            and_(
                Exam.is_published == True,
                Exam.class_id.in_(class_ids)
            )
        )

        # Filter by status
        if status == "completed":
            # Completed: Only exams with submitted attempts by this student
            completed_exam_ids = db.query(ExamAttempt.exam_id).filter(
                and_(
                    ExamAttempt.student_id == student_id,
                    ExamAttempt.status == ExamAttemptStatus.SUBMITTED.value
                )
            ).distinct().all()
            completed_ids = [e[0] for e in completed_exam_ids]
            if completed_ids:
                # Only show completed exams that are also in student's classes
                query = base_query.filter(Exam.id.in_(completed_ids))
            else:
                # No completed exams, return empty
                return {
                    "items": [],
                    "total": 0,
                    "page": page,
                    "limit": limit,
                    "pages": 0
                }
        elif status == "available":
            # Available: published, within date range (or no date restrictions) AND not completed
            completed_exam_ids = db.query(ExamAttempt.exam_id).filter(
                and_(
                    ExamAttempt.student_id == student_id,
                    ExamAttempt.status == ExamAttemptStatus.SUBMITTED.value
                )
            ).distinct().all()
            completed_ids = [e[0] for e in completed_exam_ids]
            
            query = base_query.filter(
                and_(
                    or_(
                        Exam.start_date.is_(None),
                        Exam.start_date <= now
                    ),
                    or_(
                        Exam.end_date.is_(None),
                        Exam.end_date >= now
                    )
                )
            )
            # Exclude completed exams from available
            if completed_ids:
                query = query.filter(~Exam.id.in_(completed_ids))
        else:
            # "all" or None: show ALL published exams for student's grade/class (regardless of date or completion)
            # This includes both completed and non-completed exams
            query = base_query

        # Order and paginate
        exams = query.order_by(Exam.start_date.desc() if Exam.start_date else Exam.created_at.desc()).all()
        
        total = len(exams)
        start = (page - 1) * limit
        end = start + limit
        paginated_exams = exams[start:end]

        # Add attempt status and class info for each exam
        exam_list = []
        for exam in paginated_exams:
            attempt = db.query(ExamAttempt).filter(
                and_(
                    ExamAttempt.exam_id == exam.id,
                    ExamAttempt.student_id == student_id
                )
            ).order_by(ExamAttempt.started_at.desc()).first()
            
            # Get class name
            class_ = db.query(Class).filter(Class.id == exam.class_id).first()
            
            # Determine status based on attempt
            exam_status = "available"
            if attempt:
                if attempt.status == ExamAttemptStatus.SUBMITTED.value:
                    exam_status = "completed"
                elif attempt.status == ExamAttemptStatus.IN_PROGRESS.value:
                    exam_status = "in_progress"
            
            exam_dict = {
                "id": str(exam.id),
                "title": exam.title,
                "description": exam.description,
                "class_name": class_.name if class_ else None,
                "class_id": str(exam.class_id),
                "duration_minutes": exam.duration_minutes,
                "start_date": to_utc_z(exam.start_date) if exam.start_date else None,
                "end_date": to_utc_z(exam.end_date) if exam.end_date else None,
                "is_published": exam.is_published,
                "created_at": exam.created_at.isoformat() if exam.created_at else None,
                "status": exam_status,
                "attempt_id": str(attempt.id) if attempt else None
            }
            exam_list.append(exam_dict)

        return {
            "items": exam_list,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    @staticmethod
    def get_student_materials(
        db: Session,
        student_id: UUID,
        class_id: Optional[UUID] = None,
        page: int = 1,
        limit: int = 10
    ) -> dict:
        """Get materials available to student."""
        # Get student's enrolled class IDs
        class_ids = StudentService.get_student_classes(db, student_id)
        
        if not class_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "pages": 0
            }

        # Filter by class if provided
        if class_id:
            if class_id not in class_ids:
                raise ValidationError("Student not enrolled in this class")
            class_ids = [class_id]

        # Query materials
        query = db.query(Material).filter(
            and_(
                Material.class_id.in_(class_ids),
                Material.is_active == True
            )
        )

        materials = query.order_by(Material.uploaded_at.desc()).all()
        
        total = len(materials)
        start = (page - 1) * limit
        end = start + limit
        paginated_materials = materials[start:end]

        return {
            "items": paginated_materials,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    @staticmethod
    def generate_password(length: int = 12) -> str:
        """Generate a random password."""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Ensure it meets basic requirements
        if not any(c.isupper() for c in password):
            password = password[0].upper() + password[1:]
        if not any(c.islower() for c in password):
            password = password[0].lower() + password[1:]
        if not any(c.isdigit() for c in password):
            password = password[:-1] + '1'
        return password

    @staticmethod
    def generate_roll_number(db: Session, class_id: UUID, section_id: UUID) -> str:
        """Generate a unique roll number for a student in a class-section."""
        from app.models.class_model import Section
        # Get class and section names
        class_ = db.query(Class).filter(Class.id == class_id).first()
        section = db.query(Section).filter(Section.id == section_id).first()
        
        if not class_ or not section:
            raise ValidationError("Class or section not found")
        
        # Get the highest roll number for this class-section
        existing_rolls = db.query(StudentClass.roll_number).filter(
            and_(
                StudentClass.class_id == class_id,
                StudentClass.section_id == section_id,
                StudentClass.roll_number.isnot(None)
            )
        ).order_by(StudentClass.roll_number.desc()).all()
        
        # Extract the number part from existing rolls
        max_num = 0
        class_prefix = class_.name
        section_prefix = section.name
        
        for roll in existing_rolls:
            if roll[0]:
                # Format: CLASS-SECTION-NUMBER
                parts = roll[0].split('-')
                if len(parts) >= 3:
                    try:
                        num = int(parts[-1])
                        max_num = max(max_num, num)
                    except ValueError:
                        pass
        
        # Generate new roll number
        new_num = max_num + 1
        roll_number = f"{class_prefix}-{section_prefix}-{new_num:02d}"
        
        return roll_number

    @staticmethod
    def create_student_with_profile(
        db: Session,
        student_data: StudentRegistrationCreate,
        created_by: UUID
    ) -> User:
        """Create a new student with profile and enrollment."""
        # Check if user exists
        existing = db.query(User).filter(User.email == student_data.email).first()
        if existing:
            raise ValidationError("User with this email already exists")
        
        # Check if CNIC/B-Form already exists
        existing_profile = db.query(StudentProfile).filter(
            StudentProfile.cnic_bform_no == student_data.cnic_bform_no
        ).first()
        if existing_profile:
            raise ValidationError("Student with this CNIC/B-Form number already exists")
        
        # Generate password if not provided
        password = student_data.password
        if not password:
            password = StudentService.generate_password()
        
        # Validate password
        is_valid, error = validate_password(password)
        if not is_valid:
            raise ValidationError(error)
        
        password_hash = get_password_hash(password)
        
        # Create user
        user = User(
            email=student_data.email,
            password_hash=password_hash,
            role=UserRole.STUDENT.value,
            full_name=student_data.full_name_matric
        )
        db.add(user)
        db.flush()  # Get user.id without committing
        
        # Create profile
        profile = StudentProfile(
            user_id=user.id,
            full_name_matric=student_data.full_name_matric,
            father_name=student_data.father_name,
            cnic_bform_no=student_data.cnic_bform_no,
            date_of_birth=student_data.date_of_birth,
            gender=student_data.gender,
            nationality=student_data.nationality,
            domicile=student_data.domicile,
            religion=student_data.religion,
            blood_group=student_data.blood_group,
            marital_status=student_data.marital_status,
            mobile_number=student_data.mobile_number,
            permanent_address=student_data.permanent_address,
            postal_address=student_data.postal_address,
            province=student_data.province,
            city_district=student_data.city_district,
            emergency_contact_person=student_data.emergency_contact_person,
            emergency_contact_number=student_data.emergency_contact_number
        )
        db.add(profile)
        
        # Generate roll number
        roll_number = StudentService.generate_roll_number(
            db, student_data.class_id, student_data.section_id
        )
        
        # Create enrollment
        enrollment = StudentClass(
            student_id=user.id,
            class_id=student_data.class_id,
            section_id=student_data.section_id,
            roll_number=roll_number
        )
        db.add(enrollment)
        
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def get_all_students(
        db: Session,
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        class_id: Optional[UUID] = None,
        section_id: Optional[UUID] = None
    ) -> dict:
        """Get all students with pagination and filters."""
        query = db.query(User).filter(User.role == UserRole.STUDENT.value)
        
        if class_id:
            query = query.join(StudentClass).filter(StudentClass.class_id == class_id)
        
        if section_id:
            if not class_id:
                query = query.join(StudentClass)
            query = query.filter(StudentClass.section_id == section_id)
        
        if search:
            query = query.filter(
                or_(
                    User.full_name.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%")
                )
            )
        
        if class_id or section_id:
            query = query.distinct(User.id)
        
        total = query.count()
        students = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        
        return paginate_response(students, page, limit, total)

    @staticmethod
    def get_student_by_id(db: Session, student_id: UUID) -> User:
        """Get student user by ID."""
        user = db.query(User).filter(
            and_(
                User.id == student_id,
                User.role == UserRole.STUDENT.value
            )
        ).first()
        if not user:
            raise NotFoundError("Student not found")
        return user

    @staticmethod
    def update_student_profile(
        db: Session,
        student_id: UUID,
        profile_data: StudentUpdate
    ) -> StudentProfile:
        """Update student profile information."""
        from datetime import date
        
        # Verify student exists
        user = StudentService.get_student_by_id(db, student_id)
        
        # Get or create profile
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
        
        if not profile:
            raise NotFoundError("Student profile not found")
        
        # Update profile fields - exclude_unset=True means only send fields that were actually provided
        update_data = profile_data.model_dump(exclude_unset=True)
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Updating student profile {user.id} with data: {update_data}")
        
        # Check CNIC uniqueness if being updated
        if 'cnic_bform_no' in update_data and update_data['cnic_bform_no']:
            existing = db.query(StudentProfile).filter(
                and_(
                    StudentProfile.cnic_bform_no == update_data['cnic_bform_no'],
                    StudentProfile.user_id != user.id
                )
            ).first()
            if existing:
                raise ValidationError("CNIC/B-Form number already in use")
        
        # Update profile fields one by one with explicit logging
        updated_fields = []
        for key, value in update_data.items():
            if hasattr(profile, key):
                if value is not None:
                    old_value = getattr(profile, key, None)
                    setattr(profile, key, value)
                    updated_fields.append(f"{key}: {old_value} -> {value}")
                else:
                    # Handle None values - only update if field is nullable
                    if key in ['postal_address', 'blood_group']:  # These are nullable
                        setattr(profile, key, value)
                        updated_fields.append(f"{key}: cleared")
        
        logger.info(f"Updated fields: {updated_fields}")
        
        # Update updated_at timestamp manually
        profile.updated_at = datetime.now(timezone.utc)
        
        # Update user full_name if profile full_name_matric is updated
        if 'full_name_matric' in update_data and update_data['full_name_matric']:
            user.full_name = update_data['full_name_matric']
            logger.info(f"Updated user full_name to: {update_data['full_name_matric']}")
        
        try:
            db.flush()  # Stage all changes without committing
            logger.info(f"Flushed changes to database")
            db.commit()  # Commit all changes
            logger.info(f"Committed changes to database")
            db.refresh(profile)  # Refresh to get latest data
            db.refresh(user)  # Refresh user as well
            logger.info(f"Profile updated successfully: {profile.id}")
            return profile
        except Exception as e:
            db.rollback()
            import traceback
            logger.error(f"Error updating profile: {e}")
            traceback.print_exc()
            raise ValidationError(f"Failed to update profile: {str(e)}")

    @staticmethod
    def change_student_password(
        db: Session,
        student_id: UUID,
        current_password: str,
        new_password: str
    ):
        """Change student password with current password verification."""
        from app.utils.security import verify_password
        
        user = StudentService.get_student_by_id(db, student_id)
        
        # Verify current password
        if not user.password_hash or not verify_password(current_password, user.password_hash):
            raise ValidationError("Current password is incorrect")
        
        # Validate new password
        is_valid, error = validate_password(new_password)
        if not is_valid:
            raise ValidationError(error)
        
        # Update password
        user.password_hash = get_password_hash(new_password)
        db.commit()
