-- Create initial admin user
-- Password: Admin@123 (should be hashed using bcrypt in the backend)
-- The password_hash here is a placeholder - replace with actual bcrypt hash
-- Use: from passlib.context import CryptContext; pwd_context.hash("Admin@123")
-- 
-- IMPORTANT: After creating the backend, generate the actual bcrypt hash
-- and update this seed script before running it in production

-- Example command to generate hash (Python):
-- python -c "from passlib.context import CryptContext; pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto'); print(pwd_context.hash('Admin@123'))"

-- Real bcrypt hash for password: Admin@123
INSERT INTO users (email, password_hash, role, email_verified, is_active, full_name)
VALUES (
    'admin@examini.com',
    '$2b$12$vUA85SxQWePiLAgDRW6VKO/Ysrt5z4dlWHJVLRsQKl.34fdcAF0wC',
    'admin',
    TRUE,
    TRUE,
    'System Administrator'
) ON CONFLICT (email) DO NOTHING;

