from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.api.deps import get_current_user
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.schemas.auth import (
    LoginSchema, GoogleAuthSchema, TokenResponse, RefreshTokenSchema,
    PasswordResetRequest, PasswordResetSchema
)
from app.schemas.user import UserResponse, UserUpdate
from app.schemas.common import MessageResponse
from app.models.user import User

router = APIRouter()


@router.post("/login", response_model=dict)
async def login(
    login_data: LoginSchema,
    db: Session = Depends(get_db)
):
    """Login with email and password."""
    user, access_token, refresh_token = AuthService.login(
        db, login_data.email, login_data.password
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }


@router.post("/google", response_model=dict)
async def google_auth(
    google_data: GoogleAuthSchema,
    db: Session = Depends(get_db)
):
    """Login with Google OAuth."""
    user, access_token, refresh_token = AuthService.verify_google_token(
        db, google_data.token
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    token_data: RefreshTokenSchema,
    db: Session = Depends(get_db)
):
    """Refresh access token."""
    access_token, refresh_token = AuthService.refresh_access_token(
        db, token_data.refresh_token
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    refresh_token: RefreshTokenSchema,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Logout user."""
    AuthService.logout(db, str(current_user.id), refresh_token.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """Request password reset."""
    AuthService.request_password_reset(db, request.email)
    return MessageResponse(message="Password reset email sent")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    reset_data: PasswordResetSchema,
    db: Session = Depends(get_db)
):
    """Reset password with token."""
    AuthService.reset_password(db, reset_data.token, reset_data.new_password)
    return MessageResponse(message="Password reset successfully")


@router.get("/profile", response_model=dict)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user profile with full details (including student profile if student)."""
    from app.models.student_profile import StudentProfile
    from app.models.class_model import StudentClass, Class, Section
    from app.schemas.student import StudentProfileResponse
    
    user_data = UserResponse.model_validate(current_user).model_dump()
    
    # If user is a student, include profile and enrollment details
    if current_user.role == 'student':
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
        enrollments = db.query(StudentClass).filter(StudentClass.student_id == current_user.id).all()
        
        enrollment_list = []
        for enrollment in enrollments:
            class_obj = db.query(Class).filter(Class.id == enrollment.class_id).first()
            section = db.query(Section).filter(Section.id == enrollment.section_id).first() if enrollment.section_id else None
            
            enrollment_list.append({
                "id": str(enrollment.id),
                "class_id": str(enrollment.class_id),
                "class_name": class_obj.name if class_obj else None,
                "section_id": str(enrollment.section_id) if enrollment.section_id else None,
                "section_name": section.name if section else None,
                "roll_number": enrollment.roll_number,
                "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
            })
        
        user_data["profile"] = StudentProfileResponse.model_validate(profile).model_dump() if profile else None
        user_data["enrollments"] = enrollment_list
    
    return user_data


@router.put("/profile", response_model=dict)
async def update_profile(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user profile."""
    # Prevent changing email if it already exists for another user
    if user_data.email and user_data.email != current_user.email:
        existing = db.query(User).filter(User.email == user_data.email).first()
        if existing:
            raise HTTPException(status_code=400, detail="User with this email already exists")
    
    # Update user
    if user_data.email:
        current_user.email = user_data.email
    if user_data.full_name is not None:
        current_user.full_name = user_data.full_name
    
    db.commit()
    db.refresh(current_user)
    
    # Return updated user data with profile if student
    user_response = UserResponse.model_validate(current_user).model_dump()
    
    # If student, also include profile data
    if current_user.role == 'student':
        from app.models.student_profile import StudentProfile
        from app.models.class_model import StudentClass, Class, Section
        from app.schemas.student import StudentProfileResponse
        
        profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
        enrollments = db.query(StudentClass).filter(StudentClass.student_id == current_user.id).all()
        
        enrollment_list = []
        for enrollment in enrollments:
            class_obj = db.query(Class).filter(Class.id == enrollment.class_id).first()
            section = db.query(Section).filter(Section.id == enrollment.section_id).first() if enrollment.section_id else None
            
            enrollment_list.append({
                "id": str(enrollment.id),
                "class_id": str(enrollment.class_id),
                "class_name": class_obj.name if class_obj else None,
                "section_id": str(enrollment.section_id) if enrollment.section_id else None,
                "section_name": section.name if section else None,
                "roll_number": enrollment.roll_number,
                "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
            })
        
        user_response["profile"] = StudentProfileResponse.model_validate(profile).model_dump() if profile else None
        user_response["enrollments"] = enrollment_list
    
    return user_response


@router.put("/profile/student", response_model=dict)
async def update_student_profile(
    profile_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current student's profile information."""
    if current_user.role != 'student':
        raise HTTPException(status_code=403, detail="Only students can update their profile")
    
    from app.schemas.student import StudentUpdate
    from app.services.student_service import StudentService
    from app.models.student_profile import StudentProfile
    from app.models.class_model import StudentClass, Class, Section
    from app.schemas.student import StudentProfileResponse
    import traceback
    
    try:
        # Validate and update profile
        update_data = StudentUpdate.model_validate(profile_data)
        profile = StudentService.update_student_profile(db, current_user.id, update_data)
        
        # Refresh user to get updated full_name if it was changed
        db.refresh(current_user)
        
        # Return updated profile data
        user_data = UserResponse.model_validate(current_user).model_dump()
        enrollments = db.query(StudentClass).filter(StudentClass.student_id == current_user.id).all()
        
        enrollment_list = []
        for enrollment in enrollments:
            class_obj = db.query(Class).filter(Class.id == enrollment.class_id).first()
            section = db.query(Section).filter(Section.id == enrollment.section_id).first() if enrollment.section_id else None
            
            enrollment_list.append({
                "id": str(enrollment.id),
                "class_id": str(enrollment.class_id),
                "class_name": class_obj.name if class_obj else None,
                "section_id": str(enrollment.section_id) if enrollment.section_id else None,
                "section_name": section.name if section else None,
                "roll_number": enrollment.roll_number,
                "enrolled_at": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else None,
            })
        
        user_data["profile"] = StudentProfileResponse.model_validate(profile).model_dump()
        user_data["enrollments"] = enrollment_list
        
        return user_data
    except Exception as e:
        print(f"Error updating student profile: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")


@router.delete("/profile", response_model=MessageResponse)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete current user account (soft delete)."""
    UserService.delete_user(db, current_user.id)
    return MessageResponse(message="Account deleted successfully")

