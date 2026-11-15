-- ============================================================================
-- AI-Based Timetable Generation System aligned with NEP 2020
-- Multidisciplinary Education Structures - Supabase (PostgreSQL) Schema
-- ============================================================================

-- 1. Departments Table
CREATE TABLE IF NOT EXISTS departments (
    department_id VARCHAR(50) PRIMARY KEY,
    department_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Students Table
CREATE TABLE IF NOT EXISTS students (
    student_id VARCHAR(50) PRIMARY KEY,
    student_name VARCHAR(255) NOT NULL,
    department_id VARCHAR(50) REFERENCES departments(department_id) ON DELETE RESTRICT,
    year INT DEFAULT 1,
    section VARCHAR(20) DEFAULT 'A',
    student_group VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Faculty Table
CREATE TABLE IF NOT EXISTS faculty (
    faculty_id VARCHAR(50) PRIMARY KEY,
    faculty_name VARCHAR(255) NOT NULL,
    department_id VARCHAR(50) REFERENCES departments(department_id) ON DELETE RESTRICT,
    max_weekly_periods INT DEFAULT 16,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Classrooms Table
CREATE TABLE IF NOT EXISTS classrooms (
    classroom_id VARCHAR(50) PRIMARY KEY,
    classroom_name VARCHAR(100) NOT NULL,
    room_type VARCHAR(50) NOT NULL, -- 'Classroom', 'Computer Lab', 'Electronics Lab'
    capacity INT NOT NULL,
    building VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Courses Table (NEP 2020 Multidisciplinary Categorization)
CREATE TABLE IF NOT EXISTS courses (
    course_id VARCHAR(50) PRIMARY KEY,
    course_name VARCHAR(255) NOT NULL,
    department_id VARCHAR(50) REFERENCES departments(department_id) ON DELETE RESTRICT,
    course_type VARCHAR(50) NOT NULL, -- 'Major', 'Laboratory', 'Open Elective', 'Interdisciplinary', 'Skill Enhancement'
    faculty_id VARCHAR(50) REFERENCES faculty(faculty_id) ON DELETE RESTRICT,
    weekly_sessions INT NOT NULL DEFAULT 3,
    duration_periods INT NOT NULL DEFAULT 1,
    required_room_type VARCHAR(50) NOT NULL DEFAULT 'Classroom',
    expected_enrolment INT NOT NULL DEFAULT 40,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Time Slots Table
CREATE TABLE IF NOT EXISTS time_slots (
    time_slot_id VARCHAR(50) PRIMARY KEY,
    day VARCHAR(20) NOT NULL,
    period_id VARCHAR(20) NOT NULL,
    period_number INT NOT NULL,
    start_time VARCHAR(20) NOT NULL,
    end_time VARCHAR(20) NOT NULL,
    is_teaching_slot INT DEFAULT 1,
    UNIQUE (day, period_id)
);

-- 7. Faculty Availability Table
CREATE TABLE IF NOT EXISTS faculty_availability (
    id SERIAL PRIMARY KEY,
    faculty_id VARCHAR(50) REFERENCES faculty(faculty_id) ON DELETE CASCADE,
    day VARCHAR(20) NOT NULL,
    period_id VARCHAR(20) NOT NULL,
    is_available INT DEFAULT 1,
    UNIQUE (faculty_id, day, period_id)
);

-- 8. Student Enrollments Table
CREATE TABLE IF NOT EXISTS student_enrollments (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(50) REFERENCES students(student_id) ON DELETE CASCADE,
    course_id VARCHAR(50) REFERENCES courses(course_id) ON DELETE CASCADE,
    semester VARCHAR(50) NOT NULL,
    UNIQUE (student_id, course_id, semester)
);

-- 9. Scheduling Constraints & Weights Configuration Table
CREATE TABLE IF NOT EXISTS constraints (
    constraint_name VARCHAR(100) PRIMARY KEY,
    constraint_value TEXT NOT NULL,
    constraint_type VARCHAR(50) NOT NULL, -- 'Hard', 'Soft', 'Setting', 'Weight'
    description TEXT
);

-- 10. Timetable Versions Table (Version History & Workflow)
CREATE TABLE IF NOT EXISTS timetable_versions (
    version_id VARCHAR(50) PRIMARY KEY,
    version_number INT NOT NULL,
    version_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'Draft', -- 'Draft', 'Approved', 'Published'
    notes TEXT,
    metrics JSONB DEFAULT '{}'::jsonb
);

-- 11. Timetable Entries Table (Generated Sessions)
CREATE TABLE IF NOT EXISTS timetable_entries (
    entry_id SERIAL PRIMARY KEY,
    version_id VARCHAR(50) REFERENCES timetable_versions(version_id) ON DELETE CASCADE,
    session_id VARCHAR(100) NOT NULL,
    course_id VARCHAR(50) REFERENCES courses(course_id) ON DELETE RESTRICT,
    faculty_id VARCHAR(50) REFERENCES faculty(faculty_id) ON DELETE RESTRICT,
    classroom_id VARCHAR(50) REFERENCES classrooms(classroom_id) ON DELETE RESTRICT,
    day VARCHAR(20) NOT NULL,
    period_id VARCHAR(20) NOT NULL,
    duration_periods INT NOT NULL DEFAULT 1,
    time_slot_id VARCHAR(50) REFERENCES time_slots(time_slot_id) ON DELETE RESTRICT
);

-- 12. Approval Records Table (Audit Trail)
CREATE TABLE IF NOT EXISTS approval_records (
    approval_id SERIAL PRIMARY KEY,
    version_id VARCHAR(50) REFERENCES timetable_versions(version_id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL, -- 'Draft Created', 'Approved', 'Published', 'Rejected'
    performed_by VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    comments TEXT
);

-- Indexes for Fast Query Performance
CREATE INDEX IF NOT EXISTS idx_tt_entries_version ON timetable_entries(version_id);
CREATE INDEX IF NOT EXISTS idx_tt_entries_course ON timetable_entries(course_id);
CREATE INDEX IF NOT EXISTS idx_tt_entries_faculty ON timetable_entries(faculty_id);
CREATE INDEX IF NOT EXISTS idx_tt_entries_classroom ON timetable_entries(classroom_id);
CREATE INDEX IF NOT EXISTS idx_tt_entries_day_period ON timetable_entries(day, period_id);
CREATE INDEX IF NOT EXISTS idx_enroll_student ON student_enrollments(student_id);
CREATE INDEX IF NOT EXISTS idx_enroll_course ON student_enrollments(course_id);
CREATE INDEX IF NOT EXISTS idx_fac_avail ON faculty_availability(faculty_id, day, period_id);
