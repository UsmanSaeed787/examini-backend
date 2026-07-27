from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from uuid import uuid4
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from app.models.user import User
from app.models.auth import Session as SessionModel, PasswordReset
from app.utils.security import verify_password, get_password_hash, create_access_token, create_refresh_token, verify_token, validate_password
from app.utils.constants import UserRole
from app.middleware.error_handler import AuthenticationError, NotFoundError
from app.schemas.auth import TokenResponse
from app.config import settings


class AuthService:
    """Service for authentication operations."""
    
    @staticmethod
    def login(db: Session, email: str, password: str) -> tuple[User, str, str]:
        """Authenticate user with email and password."""
        user = db.query(User).filter(User.email == email).first()
        if not user or not user.password_hash:
            raise AuthenticationError("Invalid email or password")
        
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        
        if not user.is_active:
            raise AuthenticationError("User account is inactive")
        
        # Create tokens
        access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})
        
        # Store refresh token
        expires_at = datetime.utcnow() + timedelta(days=7)
        session = SessionModel(
            id=uuid4(),
            user_id=user.id,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        db.add(session)
        db.commit()
        
        return user, access_token, refresh_token
    
    @staticmethod
    def verify_google_token(db: Session, google_token: str) -> tuple[User, str, str]:
        """Verify Google OAuth token and login existing user only."""
        try:
            # Verify the Google ID token
            if not settings.google_client_id:
                raise AuthenticationError("Google OAuth is not configured")
            
            request = google_requests.Request()
            # Add clock skew tolerance (60 seconds) to handle time differences between client and server
            idinfo = id_token.verify_oauth2_token(
                google_token,
                request,
                settings.google_client_id,
                clock_skew_in_seconds=60  # Allow 60 seconds tolerance for clock differences
            )
            
            # Extract user information from Google token
            google_id = idinfo.get('sub')
            email = idinfo.get('email')
            name = idinfo.get('name')
            picture = idinfo.get('picture')
            
            if not email:
                raise AuthenticationError("Email not provided by Google")
            
            # Check if user exists - only allow existing users to login
            user = db.query(User).filter(User.email == email).first()
            
            if not user:
                raise AuthenticationError("No account found with this email. Please contact administrator to create an account.")
            
            # Update existing user with Google info if needed
            if not user.google_id:
                user.google_id = google_id
            if picture and not user.profile_image_url:
                user.profile_image_url = picture
            if not user.email_verified:
                user.email_verified = True
            db.commit()
            db.refresh(user)
            
            if not user.is_active:
                raise AuthenticationError("User account is inactive")
            
            # Create tokens
            access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
            refresh_token = create_refresh_token(data={"sub": str(user.id)})
            
            # Store refresh token
            expires_at = datetime.utcnow() + timedelta(days=7)
            session = SessionModel(
                id=uuid4(),
                user_id=user.id,
                refresh_token=refresh_token,
                expires_at=expires_at
            )
            db.add(session)
            db.commit()
            
            return user, access_token, refresh_token
            
        except ValueError as e:
            # Invalid token
            raise AuthenticationError(f"Invalid Google token: {str(e)}")
        except AuthenticationError:
            # Re-raise authentication errors as-is
            raise
        except Exception as e:
            raise AuthenticationError(f"Google authentication failed: {str(e)}")
    
    @staticmethod
    def refresh_access_token(db: Session, refresh_token: str) -> tuple[str, str]:
        """Refresh access token using refresh token."""
        payload = verify_token(refresh_token, "refresh")
        if not payload:
            raise AuthenticationError("Invalid refresh token")
        
        user_id = payload.get("sub")
        session = db.query(SessionModel).filter(
            SessionModel.refresh_token == refresh_token,
            SessionModel.expires_at > datetime.utcnow()
        ).first()
        
        if not session or str(session.user_id) != user_id:
            raise AuthenticationError("Invalid or expired refresh token")
        
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            raise AuthenticationError("User not found")
        
        # Create new tokens
        access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
        new_refresh_token = create_refresh_token(data={"sub": str(user.id)})
        
        # Update session
        session.refresh_token = new_refresh_token
        session.expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        
        return access_token, new_refresh_token
    
    @staticmethod
    def logout(db: Session, user_id: str, refresh_token: Optional[str] = None):
        """Logout user by invalidating refresh token."""
        if refresh_token:
            session = db.query(SessionModel).filter(SessionModel.refresh_token == refresh_token).first()
            if session:
                db.delete(session)
        else:
            # Delete all sessions for user
            sessions = db.query(SessionModel).filter(SessionModel.user_id == user_id).all()
            for session in sessions:
                db.delete(session)
        db.commit()
    
    @staticmethod
    def request_password_reset(db: Session, email: str):
        """Request password reset."""
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Don't reveal if user exists
            return
        
        # Generate reset token
        token = str(uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)
        
        reset_request = PasswordReset(
            id=uuid4(),
            user_id=user.id,
            token=token,
            expires_at=expires_at
        )
        db.add(reset_request)
        db.commit()
        
        # TODO: Send email with reset link
        return token
    
    @staticmethod
    def reset_password(db: Session, token: str, new_password: str):
        """Reset password using token."""
        reset_request = db.query(PasswordReset).filter(
            PasswordReset.token == token,
            PasswordReset.expires_at > datetime.utcnow(),
            PasswordReset.used_at.is_(None)
        ).first()
        
        if not reset_request:
            raise AuthenticationError("Invalid or expired reset token")
        
        # Validate password
        is_valid, error = validate_password(new_password)
        if not is_valid:
            raise AuthenticationError(error)
        
        # Update password
        user = db.query(User).filter(User.id == reset_request.user_id).first()
        if not user:
            raise NotFoundError("User not found")
        
        user.password_hash = get_password_hash(new_password)
        reset_request.used_at = datetime.utcnow()
        db.commit()

