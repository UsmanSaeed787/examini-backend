from sqlalchemy import Column, String, Date, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Personal Information
    full_name_matric = Column(String(255), nullable=False)
    father_name = Column(String(255), nullable=False)
    cnic_bform_no = Column(String(20), nullable=False, unique=True, index=True)
    date_of_birth = Column(Date, nullable=False)
    gender = Column(String(20), nullable=False)  # Male, Female, Other
    nationality = Column(String(50), nullable=False)  # Pakistani, Dual National
    domicile = Column(String(50), nullable=False)  # Punjab, Sindh, KP, Balochistan, AJK, GB
    religion = Column(String(50), nullable=False)
    blood_group = Column(String(5))
    marital_status = Column(String(20), nullable=False)  # Single, Married
    
    # Contact Information
    mobile_number = Column(String(15), nullable=False)
    permanent_address = Column(String, nullable=False)
    postal_address = Column(String)
    province = Column(String(50), nullable=False)
    city_district = Column(String(100), nullable=False)
    
    # Emergency Contact
    emergency_contact_person = Column(String(255), nullable=False)
    emergency_contact_number = Column(String(15), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default='now()')
    updated_at = Column(DateTime(timezone=True), server_default='now()', onupdate='now()')
    
    # Relationships
    user = relationship("User", back_populates="student_profile", uselist=False)
    
    # Check constraints (will be added via migration)
    __table_args__ = (
        CheckConstraint(
            "gender IN ('Male', 'Female', 'Other')",
            name='check_gender'
        ),
        CheckConstraint(
            "nationality IN ('Pakistani', 'Dual National')",
            name='check_nationality'
        ),
        CheckConstraint(
            "domicile IN ('Punjab', 'Sindh', 'KP', 'Balochistan', 'AJK', 'GB')",
            name='check_domicile'
        ),
        CheckConstraint(
            "marital_status IN ('Single', 'Married')",
            name='check_marital_status'
        ),
        CheckConstraint(
            "date_of_birth <= CURRENT_DATE",
            name='check_date_of_birth_not_future'
        ),
    )

