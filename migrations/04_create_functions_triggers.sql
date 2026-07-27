-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_classes_updated_at BEFORE UPDATE ON classes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sections_updated_at BEFORE UPDATE ON sections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_materials_updated_at BEFORE UPDATE ON materials
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_exams_updated_at BEFORE UPDATE ON exams
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_question_bank_updated_at BEFORE UPDATE ON question_bank
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to automatically calculate exam result on submission
CREATE OR REPLACE FUNCTION calculate_exam_result()
RETURNS TRIGGER AS $$
DECLARE
    v_total_score DECIMAL(10,2);
    v_max_score DECIMAL(10,2);
    v_percentage DECIMAL(5,2);
    v_grade VARCHAR(10);
    v_passed BOOLEAN;
BEGIN
    -- Only calculate when exam is submitted
    IF NEW.status = 'submitted' AND OLD.status != 'submitted' THEN
        -- Calculate total score and max score
        SELECT 
            COALESCE(SUM(er.points_earned), 0),
            COALESCE(SUM(q.points), 0)
        INTO v_total_score, v_max_score
        FROM exam_responses er
        JOIN questions q ON er.question_id = q.id
        WHERE er.attempt_id = NEW.id;

        -- Calculate percentage
        IF v_max_score > 0 THEN
            v_percentage := (v_total_score / v_max_score) * 100;
        ELSE
            v_percentage := 0;
        END IF;

        -- Determine grade and passed status
        IF v_percentage >= 90 THEN
            v_grade := 'A+';
            v_passed := TRUE;
        ELSIF v_percentage >= 80 THEN
            v_grade := 'A';
            v_passed := TRUE;
        ELSIF v_percentage >= 70 THEN
            v_grade := 'B';
            v_passed := TRUE;
        ELSIF v_percentage >= 60 THEN
            v_grade := 'C';
            v_passed := TRUE;
        ELSIF v_percentage >= 50 THEN
            v_grade := 'D';
            v_passed := TRUE;
        ELSE
            v_grade := 'F';
            v_passed := FALSE;
        END IF;

        -- Insert or update exam result
        INSERT INTO exam_results (
            attempt_id, total_score, max_score, percentage, grade, passed
        ) VALUES (
            NEW.id, v_total_score, v_max_score, v_percentage, v_grade, v_passed
        )
        ON CONFLICT (attempt_id) DO UPDATE SET
            total_score = EXCLUDED.total_score,
            max_score = EXCLUDED.max_score,
            percentage = EXCLUDED.percentage,
            grade = EXCLUDED.grade,
            passed = EXCLUDED.passed,
            created_at = CURRENT_TIMESTAMP;
    END IF;

    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for automatic result calculation
CREATE TRIGGER calculate_result_on_submit
    AFTER UPDATE OF status ON exam_attempts
    FOR EACH ROW
    WHEN (NEW.status = 'submitted')
    EXECUTE FUNCTION calculate_exam_result();

-- Function to clean up expired sessions
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS void AS $$
BEGIN
    DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP;
END;
$$ language 'plpgsql';

