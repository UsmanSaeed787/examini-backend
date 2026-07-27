-- Users indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_google_id ON users(google_id) WHERE google_id IS NOT NULL;

-- Sessions indexes
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_refresh_token ON sessions(refresh_token);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);

-- Password resets indexes
CREATE INDEX idx_password_resets_token ON password_resets(token);
CREATE INDEX idx_password_resets_user_id ON password_resets(user_id);

-- Classes indexes
CREATE INDEX idx_classes_name ON classes(name);

-- Sections indexes
CREATE INDEX idx_sections_class_id ON sections(class_id);

-- Teacher classes indexes
CREATE INDEX idx_teacher_classes_teacher_id ON teacher_classes(teacher_id);
CREATE INDEX idx_teacher_classes_class_id ON teacher_classes(class_id);

-- Student classes indexes
CREATE INDEX idx_student_classes_student_id ON student_classes(student_id);
CREATE INDEX idx_student_classes_class_id ON student_classes(class_id);
CREATE INDEX idx_student_classes_section_id ON student_classes(section_id);

-- Materials indexes
CREATE INDEX idx_materials_teacher_id ON materials(teacher_id);
CREATE INDEX idx_materials_class_id ON materials(class_id);
CREATE INDEX idx_materials_uploaded_at ON materials(uploaded_at);

-- Exams indexes
CREATE INDEX idx_exams_teacher_id ON exams(teacher_id);
CREATE INDEX idx_exams_class_id ON exams(class_id);
CREATE INDEX idx_exams_start_date ON exams(start_date);
CREATE INDEX idx_exams_end_date ON exams(end_date);
CREATE INDEX idx_exams_is_published ON exams(is_published);

-- Exam sections indexes
CREATE INDEX idx_exam_sections_exam_id ON exam_sections(exam_id);
CREATE INDEX idx_exam_sections_section_id ON exam_sections(section_id);

-- Questions indexes
CREATE INDEX idx_questions_exam_id ON questions(exam_id);
CREATE INDEX idx_questions_difficulty ON questions(difficulty_level);

-- Question options indexes
CREATE INDEX idx_question_options_question_id ON question_options(question_id);

-- Question bank indexes
CREATE INDEX idx_question_bank_teacher_id ON question_bank(teacher_id);
CREATE INDEX idx_question_bank_tags ON question_bank USING GIN(tags);
CREATE INDEX idx_question_bank_difficulty ON question_bank(difficulty_level);

-- Exam attempts indexes
CREATE INDEX idx_exam_attempts_exam_id ON exam_attempts(exam_id);
CREATE INDEX idx_exam_attempts_student_id ON exam_attempts(student_id);
CREATE INDEX idx_exam_attempts_status ON exam_attempts(status);

-- Exam responses indexes
CREATE INDEX idx_exam_responses_attempt_id ON exam_responses(attempt_id);
CREATE INDEX idx_exam_responses_question_id ON exam_responses(question_id);

-- Exam results indexes
CREATE INDEX idx_exam_results_attempt_id ON exam_results(attempt_id);
CREATE INDEX idx_exam_results_percentage ON exam_results(percentage);

-- Exam permissions indexes
CREATE INDEX idx_exam_permissions_exam_id ON exam_permissions(exam_id);

-- Notifications indexes
CREATE INDEX idx_notifications_user_id ON notifications(user_id);
CREATE INDEX idx_notifications_is_read ON notifications(is_read);
CREATE INDEX idx_notifications_created_at ON notifications(created_at);

-- Audit logs indexes
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_logs_created_at ON audit_logs(created_at);

