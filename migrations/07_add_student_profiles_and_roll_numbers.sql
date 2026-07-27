-- Migration: Add student profiles and roll numbers
-- Description: Creates student_profiles table for detailed student information
--              and adds roll_number to student_classes table

-- Create student_profiles table
CREATE TABLE IF NOT EXISTS student_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    full_name_matric VARCHAR(255) NOT NULL,
    father_name VARCHAR(255) NOT NULL,
    cnic_bform_no VARCHAR(20) NOT NULL UNIQUE,
    date_of_birth DATE NOT NULL,
    gender VARCHAR(20) NOT NULL CHECK (gender IN ('Male', 'Female', 'Other')),
    nationality VARCHAR(50) NOT NULL CHECK (nationality IN ('Pakistani', 'Dual National')),
    domicile VARCHAR(50) NOT NULL CHECK (domicile IN ('Punjab', 'Sindh', 'KP', 'Balochistan', 'AJK', 'GB')),
    religion VARCHAR(50) NOT NULL,
    blood_group VARCHAR(5),
    marital_status VARCHAR(20) NOT NULL CHECK (marital_status IN ('Single', 'Married')),
    mobile_number VARCHAR(15) NOT NULL,
    permanent_address TEXT NOT NULL,
    postal_address TEXT,
    province VARCHAR(50) NOT NULL,
    city_district VARCHAR(100) NOT NULL,
    emergency_contact_person VARCHAR(255) NOT NULL,
    emergency_contact_number VARCHAR(15) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for student_profiles
CREATE INDEX IF NOT EXISTS idx_student_profiles_user_id ON student_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_student_profiles_cnic_bform ON student_profiles(cnic_bform_no);
CREATE INDEX IF NOT EXISTS idx_student_profiles_class_section ON student_profiles(user_id);

-- Add roll_number to student_classes table
ALTER TABLE student_classes 
ADD COLUMN IF NOT EXISTS roll_number VARCHAR(50);

-- Create unique index for roll_number per class-section combination
CREATE UNIQUE INDEX IF NOT EXISTS idx_student_classes_roll_number 
ON student_classes(class_id, section_id, roll_number) 
WHERE roll_number IS NOT NULL;

-- Create index on roll_number
CREATE INDEX IF NOT EXISTS idx_student_classes_roll_number_simple 
ON student_classes(roll_number);

-- Function to generate roll number
CREATE OR REPLACE FUNCTION generate_roll_number(
    p_class_id UUID,
    p_section_id UUID
) RETURNS VARCHAR(50) AS $$
DECLARE
    v_class_name VARCHAR(255);
    v_section_name VARCHAR(255);
    v_next_seq INTEGER;
    v_roll_number VARCHAR(50);
BEGIN
    -- Get class and section names
    SELECT name INTO v_class_name FROM classes WHERE id = p_class_id;
    SELECT name INTO v_section_name FROM sections WHERE id = p_section_id;
    
    -- Get next sequence number for this class-section
    SELECT COALESCE(MAX(CAST(SPLIT_PART(roll_number, '-', 3) AS INTEGER)), 0) + 1
    INTO v_next_seq
    FROM student_classes
    WHERE class_id = p_class_id 
    AND section_id = p_section_id 
    AND roll_number IS NOT NULL;
    
    -- Format: CLASS-SECTION-SEQ (e.g., "10-A-01")
    -- Use first part of class name and section name
    v_roll_number := LOWER(SUBSTRING(v_class_name FROM 1 FOR 10)) || '-' || 
                     LOWER(SUBSTRING(v_section_name FROM 1 FOR 10)) || '-' || 
                     LPAD(v_next_seq::TEXT, 2, '0');
    
    RETURN v_roll_number;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_student_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_student_profiles_updated_at
BEFORE UPDATE ON student_profiles
FOR EACH ROW
EXECUTE FUNCTION update_student_profiles_updated_at();

-- Add constraint to ensure date_of_birth is not in the future
ALTER TABLE student_profiles 
ADD CONSTRAINT check_date_of_birth_not_future 
CHECK (date_of_birth <= CURRENT_DATE);

-- Add constraint to ensure date_of_birth makes sense (minimum age 5 years)
ALTER TABLE student_profiles 
ADD CONSTRAINT check_date_of_birth_minimum_age 
CHECK (date_of_birth <= CURRENT_DATE - INTERVAL '5 years');

COMMENT ON TABLE student_profiles IS 'Detailed profile information for students';
COMMENT ON COLUMN student_profiles.full_name_matric IS 'Full name as per Matric Certificate';
COMMENT ON COLUMN student_profiles.cnic_bform_no IS 'CNIC (13 digits) or B-Form (11 digits) number';
COMMENT ON COLUMN student_classes.roll_number IS 'Auto-generated roll number in format: CLASS-SECTION-SEQ';

