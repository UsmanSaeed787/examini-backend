from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional
from uuid import UUID
from datetime import date, datetime
import re


class StudentRegistrationBase(BaseModel):
    """Base schema for student registration"""
    # Personal Information
    full_name_matric: str  # Full Name (as per Matric Certificate)
    father_name: str
    cnic_bform_no: str  # CNIC / B-Form No
    date_of_birth: date
    gender: str  # Male / Female / Other
    nationality: str  # Pakistani / Dual National
    domicile: str  # Punjab / Sindh / KP / Balochistan / AJK / GB
    religion: str
    blood_group: Optional[str] = None  # e.g., B+
    marital_status: str  # Single / Married
    
    # Contact Information
    mobile_number: str  # 03XX-XXXXXXX
    email: EmailStr
    permanent_address: str
    postal_address: Optional[str] = None  # if different
    province: str
    city_district: str
    
    # Emergency Contact
    emergency_contact_person: str
    emergency_contact_number: str
    
    # Academic Information
    class_id: UUID
    section_id: UUID
    
    @field_validator('gender')
    @classmethod
    def validate_gender(cls, v):
        allowed = ['Male', 'Female', 'Other']
        if v not in allowed:
            raise ValueError(f'Gender must be one of {allowed}')
        return v
    
    @field_validator('nationality')
    @classmethod
    def validate_nationality(cls, v):
        allowed = ['Pakistani', 'Dual National']
        if v not in allowed:
            raise ValueError('Nationality must be "Pakistani" or "Dual National"')
        return v
    
    @field_validator('domicile')
    @classmethod
    def validate_domicile(cls, v):
        allowed = ['Punjab', 'Sindh', 'KP', 'Balochistan', 'AJK', 'GB']
        if v not in allowed:
            raise ValueError(f'Domicile must be one of {allowed}')
        return v
    
    @field_validator('marital_status')
    @classmethod
    def validate_marital_status(cls, v):
        allowed = ['Single', 'Married']
        if v not in allowed:
            raise ValueError('Marital status must be "Single" or "Married"')
        return v
    
    @field_validator('cnic_bform_no')
    @classmethod
    def validate_cnic_bform(cls, v):
        # Remove dashes and spaces
        cleaned = re.sub(r'[-\s]', '', v)
        # CNIC: 13 digits, B-Form: 11 digits
        if not re.match(r'^\d{11}$|^\d{13}$', cleaned):
            raise ValueError('CNIC must be 13 digits or B-Form must be 11 digits')
        return cleaned
    
    @field_validator('mobile_number')
    @classmethod
    def validate_mobile_number(cls, v):
        # Remove dashes and spaces
        cleaned = re.sub(r'[-\s]', '', v)
        # Pakistani mobile format: 03XX-XXXXXXX (11 digits starting with 03)
        if not re.match(r'^03\d{9}$', cleaned):
            raise ValueError('Mobile number must be in format 03XX-XXXXXXX (Pakistani format)')
        return cleaned
    
    @field_validator('emergency_contact_number')
    @classmethod
    def validate_emergency_contact(cls, v):
        # Remove dashes and spaces
        cleaned = re.sub(r'[-\s]', '', v)
        # Can be mobile (03XX) or landline
        if not re.match(r'^\d{10,11}$', cleaned):
            raise ValueError('Emergency contact number must be 10-11 digits')
        return cleaned
    
    @field_validator('date_of_birth')
    @classmethod
    def validate_date_of_birth(cls, v):
        if v > date.today():
            raise ValueError('Date of birth cannot be in the future')
        # Minimum age 5 years
        from datetime import timedelta
        min_date = date.today() - timedelta(days=5*365)
        if v > min_date:
            raise ValueError('Student must be at least 5 years old')
        return v
    
    @field_validator('blood_group')
    @classmethod
    def validate_blood_group(cls, v):
        if v is not None:
            allowed = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
            if v not in allowed:
                raise ValueError(f'Blood group must be one of {allowed}')
        return v


class StudentRegistrationCreate(StudentRegistrationBase):
    """Schema for creating a new student with profile"""
    password: Optional[str] = None  # Optional, can be auto-generated


class StudentProfileResponse(BaseModel):
    """Response schema for student profile"""
    id: UUID
    user_id: UUID
    full_name_matric: str
    father_name: str
    cnic_bform_no: str
    date_of_birth: date
    gender: str
    nationality: str
    domicile: str
    religion: str
    blood_group: Optional[str]
    marital_status: str
    mobile_number: str
    permanent_address: str
    postal_address: Optional[str]
    province: str
    city_district: str
    emergency_contact_person: str
    emergency_contact_number: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class StudentEnrollmentResponse(BaseModel):
    """Response schema for student class enrollment"""
    id: UUID
    student_id: UUID
    class_id: UUID
    section_id: UUID
    roll_number: Optional[str]
    enrolled_at: datetime
    
    class Config:
        from_attributes = True


class StudentDetailResponse(BaseModel):
    """Complete student information including profile and enrollment"""
    id: UUID
    email: str
    full_name: Optional[str]
    role: str
    email_verified: bool
    is_active: bool
    created_at: datetime
    profile: Optional[StudentProfileResponse] = None
    enrollments: list[StudentEnrollmentResponse] = []
    
    class Config:
        from_attributes = True


class StudentUpdate(BaseModel):
    """Schema for updating student profile"""
    full_name_matric: Optional[str] = None
    father_name: Optional[str] = None
    cnic_bform_no: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    domicile: Optional[str] = None
    religion: Optional[str] = None
    blood_group: Optional[str] = None
    marital_status: Optional[str] = None
    mobile_number: Optional[str] = None
    permanent_address: Optional[str] = None
    postal_address: Optional[str] = None
    province: Optional[str] = None
    city_district: Optional[str] = None
    emergency_contact_person: Optional[str] = None
    emergency_contact_number: Optional[str] = None
    
    @field_validator('cnic_bform_no')
    @classmethod
    def validate_cnic_bform(cls, v):
        if v is not None:
            cleaned = re.sub(r'[-\s]', '', v)
            if not (11 <= len(cleaned) <= 13 and cleaned.isdigit()):
                raise ValueError('CNIC/B-Form must be 11-13 digits')
            return cleaned
        return v
    
    @field_validator('date_of_birth', mode='before')
    @classmethod
    def validate_date_of_birth(cls, v):
        if v is None:
            return None
        # Convert string to date if needed
        if isinstance(v, str):
            try:
                v = date.fromisoformat(v)
            except (ValueError, TypeError):
                raise ValueError('Invalid date format. Use YYYY-MM-DD format.')
        # Validate date is not in future
        if isinstance(v, date) and v > date.today():
            raise ValueError('Date of birth cannot be in the future')
        return v
    
    @field_validator('gender')
    @classmethod
    def validate_gender(cls, v):
        if v is not None and v not in ['Male', 'Female', 'Other']:
            raise ValueError('Gender must be one of: Male, Female, Other')
        return v
    
    @field_validator('nationality')
    @classmethod
    def validate_nationality(cls, v):
        if v is not None and v not in ['Pakistani', 'Dual National']:
            raise ValueError('Nationality must be one of: Pakistani, Dual National')
        return v
    
    @field_validator('domicile')
    @classmethod
    def validate_domicile(cls, v):
        if v is not None and v not in ['Punjab', 'Sindh', 'KP', 'Balochistan', 'AJK', 'GB']:
            raise ValueError('Domicile must be one of: Punjab, Sindh, KP, Balochistan, AJK, GB')
        return v
    
    @field_validator('marital_status')
    @classmethod
    def validate_marital_status(cls, v):
        if v is not None and v not in ['Single', 'Married']:
            raise ValueError('Marital status must be one of: Single, Married')
        return v
    
    @field_validator('blood_group')
    @classmethod
    def validate_blood_group(cls, v):
        if v is not None and v not in ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']:
            raise ValueError('Blood group must be one of: A+, A-, B+, B-, AB+, AB-, O+, O-')
        return v
    
    @field_validator('mobile_number')
    @classmethod
    def validate_mobile_number(cls, v):
        if v is not None:
            cleaned = re.sub(r'[-\s]', '', v)
            if not re.match(r'^03\d{9}$', cleaned):
                raise ValueError('Mobile number must be in format 03XX-XXXXXXX')
            return cleaned
        return v
    
    @field_validator('emergency_contact_number')
    @classmethod
    def validate_emergency_contact(cls, v):
        if v is not None:
            cleaned = re.sub(r'[-\s]', '', v)
            if not re.match(r'^\d{10,11}$', cleaned):
                raise ValueError('Emergency contact number must be 10-11 digits')
            return cleaned
        return v

