from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.utils.security import verify_token
from app.utils.constants import UserRole
from app.middleware.error_handler import AuthenticationError, AuthorizationError

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user."""
    token = credentials.credentials
    payload = verify_token(token, "access")
    
    if not payload:
        raise AuthenticationError("Invalid or expired token")
    
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Invalid token payload")
    
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise AuthenticationError("User not found or inactive")
    
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise AuthenticationError("User is inactive")
    return current_user


def require_role(*allowed_roles: UserRole):
    """Dependency factory for role-based access control."""
    def role_checker(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise AuthorizationError(f"Access denied. Required roles: {[r.value for r in allowed_roles]}")
        return current_user
    return role_checker


def get_admin_user(current_user: User = Depends(get_current_active_user)) -> User:
    """Get current user if admin."""
    if current_user.role != UserRole.ADMIN.value:
        raise AuthorizationError("Admin access required")
    return current_user


def get_teacher_user(current_user: User = Depends(get_current_active_user)) -> User:
    """Get current user if teacher."""
    if current_user.role != UserRole.TEACHER.value:
        raise AuthorizationError("Teacher access required")
    return current_user


def get_student_user(current_user: User = Depends(get_current_active_user)) -> User:
    """Get current user if student."""
    if current_user.role != UserRole.STUDENT.value:
        raise AuthorizationError("Student access required")
    return current_user

