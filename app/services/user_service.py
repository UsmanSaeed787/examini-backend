from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, List
from uuid import UUID
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.utils.security import get_password_hash, validate_password
from app.utils.constants import UserRole
from app.middleware.error_handler import NotFoundError, ValidationError
from app.utils.helpers import paginate_response


class UserService:
    """Service for user management operations."""
    
    @staticmethod
    def create_user(db: Session, user_data: UserCreate) -> User:
        """Create a new user."""
        # Check if user exists
        existing = db.query(User).filter(User.email == user_data.email).first()
        if existing:
            raise ValidationError("User with this email already exists")
        
        # Validate password if provided
        if user_data.password:
            is_valid, error = validate_password(user_data.password)
            if not is_valid:
                raise ValidationError(error)
            password_hash = get_password_hash(user_data.password)
        else:
            password_hash = None
        
        user = User(
            email=user_data.email,
            password_hash=password_hash,
            role=user_data.role.value,
            full_name=user_data.full_name
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    
    @staticmethod
    def get_user(db: Session, user_id: UUID) -> User:
        """Get user by ID."""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise NotFoundError("User not found")
        return user
    
    @staticmethod
    def get_users(
        db: Session,
        page: int = 1,
        limit: int = 10,
        role: Optional[UserRole] = None,
        search: Optional[str] = None
    ) -> dict:
        """Get paginated list of users."""
        query = db.query(User)
        
        # Exclude admin users from the list (admins should not see other admins)
        query = query.filter(User.role != UserRole.ADMIN.value)
        
        if role:
            query = query.filter(User.role == role.value)
        
        if search:
            query = query.filter(
                or_(
                    User.email.ilike(f"%{search}%"),
                    User.full_name.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        users = query.offset((page - 1) * limit).limit(limit).all()
        
        return paginate_response(users, page, limit, total)
    
    @staticmethod
    def update_user(db: Session, user_id: UUID, user_data: UserUpdate) -> User:
        """Update user."""
        user = UserService.get_user(db, user_id)
        
        # Prevent editing admin users
        if user.role == UserRole.ADMIN.value:
            raise ValidationError("Admin users cannot be edited")
        
        if user_data.email and user_data.email != user.email:
            existing = db.query(User).filter(User.email == user_data.email).first()
            if existing:
                raise ValidationError("User with this email already exists")
            user.email = user_data.email
        
        if user_data.full_name is not None:
            user.full_name = user_data.full_name
        
        if user_data.is_active is not None:
            user.is_active = user_data.is_active
        
        db.commit()
        db.refresh(user)
        return user
    
    @staticmethod
    def delete_user(db: Session, user_id: UUID):
        """Soft delete user."""
        user = UserService.get_user(db, user_id)
        
        # Prevent deleting admin users
        if user.role == UserRole.ADMIN.value:
            raise ValidationError("Admin users cannot be deleted")
        
        user.is_active = False
        db.commit()
    
    @staticmethod
    def bulk_create_users(db: Session, users_data: List[UserCreate]) -> dict:
        """Bulk create users."""
        created = 0
        errors = []
        
        for user_data in users_data:
            try:
                UserService.create_user(db, user_data)
                created += 1
            except Exception as e:
                errors.append(f"Error creating user {user_data.email}: {str(e)}")
        
        return {"created": created, "errors": errors}

