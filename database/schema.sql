-- ============================================================
-- database/schema.sql — SQL Server DDL for VirtualClinicDB
--
-- Run this script ONCE on an EMPTY server to create all tables.
-- Execute in SQL Server Management Studio (SSMS):
--   1. Connect to your local SQL Server instance
--   2. Open a New Query window
--   3. Paste this entire script and press F5
--
-- Or run via sqlcmd (-I is needed for the filtered indexes):
--   sqlcmd -S localhost -E -I -i schema.sql
--
-- A fresh database built from this file has the same structure as the
-- live database after database/demo_additions.sql was applied.
-- (An existing database is upgraded with demo_additions.sql, not this file.)
-- ============================================================

-- Create and select the database
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'VirtualClinicDB')
BEGIN
    CREATE DATABASE VirtualClinicDB;
    PRINT 'Database VirtualClinicDB created.';
END
GO

USE VirtualClinicDB;
GO

-- ============================================================
-- TABLE: Users (base user record for all roles)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Users')
BEGIN
    CREATE TABLE Users (
        user_id     INT IDENTITY(1,1) PRIMARY KEY,
        name        VARCHAR(100)  NOT NULL,
        email       VARCHAR(100)  NOT NULL UNIQUE,
        password    VARCHAR(255)  NOT NULL,   -- plaintext password
        role        VARCHAR(20)   NOT NULL    -- 'student' | 'teacher' | 'psychologist' | 'advisor'
                    CHECK (role IN ('student', 'teacher', 'psychologist', 'advisor')),
        created_at  DATETIME      NOT NULL DEFAULT GETDATE()
    );
    PRINT 'Table Users created.';
END
GO

-- ============================================================
-- TABLE: Sections (a class section and its class advisor)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Sections')
BEGIN
    CREATE TABLE Sections (
        section_id    INT IDENTITY(1,1) PRIMARY KEY,
        section_name  VARCHAR(50) NOT NULL UNIQUE,
        advisor_id    INT NOT NULL REFERENCES Users(user_id)
    );
    PRINT 'Table Sections created.';
END
GO

-- ============================================================
-- TABLE: Students (extends Users for student-specific data)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Students')
BEGIN
    CREATE TABLE Students (
        student_id       INT IDENTITY(1,1) PRIMARY KEY,
        user_id          INT NOT NULL UNIQUE REFERENCES Users(user_id) ON DELETE CASCADE,
        cgpa_trend       FLOAT NOT NULL DEFAULT 0.0,   -- negative = declining GPA
        attendance_drop  FLOAT NOT NULL DEFAULT 0.0,   -- positive = more absences
        section_id       INT NULL REFERENCES Sections(section_id)
    );
    PRINT 'Table Students created.';
END
GO

-- ============================================================
-- TABLE: Teachers (extends Users for teacher-specific data)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Teachers')
BEGIN
    CREATE TABLE Teachers (
        teacher_id   INT IDENTITY(1,1) PRIMARY KEY,
        user_id      INT NOT NULL UNIQUE REFERENCES Users(user_id) ON DELETE CASCADE,
        workload_hrs FLOAT NOT NULL DEFAULT 0.0,
        class_count  INT   NOT NULL DEFAULT 0
    );
    PRINT 'Table Teachers created.';
END
GO

-- ============================================================
-- TABLE: Sessions
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Sessions')
BEGIN
    CREATE TABLE Sessions (
        session_id  INT IDENTITY(1,1) PRIMARY KEY,
        user_id     INT NOT NULL REFERENCES Users(user_id),
        start_time  DATETIME NOT NULL,
        end_time    DATETIME NULL,
        status      VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'completed'))
    );
    PRINT 'Table Sessions created.';
END
GO

-- ============================================================
-- TABLE: AdvisorNotifications (flag for the class advisor, Medium risk)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'AdvisorNotifications')
BEGIN
    CREATE TABLE AdvisorNotifications (
        notification_id  INT IDENTITY(1,1) PRIMARY KEY,
        advisor_id       INT           NOT NULL REFERENCES Users(user_id),
        student_id       INT           NOT NULL REFERENCES Users(user_id),
        session_id       INT           NOT NULL REFERENCES Sessions(session_id),
        message          NVARCHAR(500) NOT NULL,
        is_read          BIT           NULL DEFAULT 0,
        created_at       DATETIME2     NULL DEFAULT GETUTCDATE()
    );
    PRINT 'Table AdvisorNotifications created.';
END
GO

-- ============================================================
-- TABLE: SensorData (pulse/PPG and blood-pressure readings; real readings only)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SensorData')
BEGIN
    CREATE TABLE SensorData (
        sensor_id    INT IDENTITY(1,1) PRIMARY KEY,
        session_id   INT         NOT NULL REFERENCES Sessions(session_id),
        data_type    VARCHAR(20) NOT NULL CHECK (data_type IN ('eeg', 'bp', 'ppg')),
        eeg_value    FLOAT       NULL,
        bp_systolic  INT         NULL,
        bp_diastolic INT         NULL,
        pulse_rate   INT         NULL,
        recorded_at  DATETIME    NOT NULL DEFAULT GETDATE()
    );
    PRINT 'Table SensorData created.';
END
GO

-- ============================================================
-- TABLE: EEG_Snapshots (band powers + stress index, one row per EEG window)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'EEG_Snapshots')
BEGIN
    CREATE TABLE EEG_Snapshots (
        snapshot_id   INT IDENTITY(1,1) PRIMARY KEY,
        session_id    INT      NOT NULL REFERENCES Sessions(session_id),
        recorded_at   DATETIME NOT NULL DEFAULT GETDATE(),
        alpha_power   FLOAT    NOT NULL DEFAULT 0,
        beta_power    FLOAT    NOT NULL DEFAULT 0,
        theta_power   FLOAT    NOT NULL DEFAULT 0,
        stress_index  FLOAT    NOT NULL DEFAULT 0,
        question_id   INT      NULL,
        question_num  INT      NULL
    );
    PRINT 'Table EEG_Snapshots created.';
END
GO

-- ============================================================
-- TABLE: Q_Stages
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Q_Stages')
BEGIN
    CREATE TABLE Q_Stages (
        stage_id      INT IDENTITY(1,1) PRIMARY KEY,
        stage_number  INT           NOT NULL UNIQUE CHECK (stage_number BETWEEN 1 AND 5),
        stage_name    VARCHAR(100)  NOT NULL,
        target_role   VARCHAR(20)   NOT NULL  -- 'student' | 'teacher' | 'both'
                      CHECK (target_role IN ('student', 'teacher', 'both')),
        threshold     FLOAT         NOT NULL  -- minimum passing score
    );
    PRINT 'Table Q_Stages created.';
END
GO

-- ============================================================
-- TABLE: Q_Questions
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Q_Questions')
BEGIN
    CREATE TABLE Q_Questions (
        question_id   INT IDENTITY(1,1) PRIMARY KEY,
        stage_id      INT           NOT NULL REFERENCES Q_Stages(stage_id),
        question_text VARCHAR(500)  NOT NULL,
        weight        FLOAT         NOT NULL DEFAULT 1.0
    );
    PRINT 'Table Q_Questions created.';
END
GO

-- ============================================================
-- TABLE: QuestionFeedback (psychologist opinion on one question)
-- Stored for later review of the questionnaire weights. Nothing in the
-- code changes Q_Questions.weight or the stage weights from this table.
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'QuestionFeedback')
BEGIN
    CREATE TABLE QuestionFeedback (
        feedback_id      INT IDENTITY(1,1) PRIMARY KEY,
        psychologist_id  INT           NOT NULL REFERENCES Users(user_id),
        question_id      INT           NOT NULL REFERENCES Q_Questions(question_id),
        usefulness_score INT           NOT NULL CHECK (usefulness_score BETWEEN 1 AND 5),
        created_at       DATETIME      NOT NULL DEFAULT GETDATE(),
        usefulness_label VARCHAR(20)   NULL,   -- 'useful' | 'less_useful' | 'irrelevant'
        comments         NVARCHAR(500) NULL,
        session_id       INT           NULL,
        updated_at       DATETIME      NULL,
        CONSTRAINT FK_QuestionFeedback_session FOREIGN KEY (session_id) REFERENCES Sessions(session_id),
        CONSTRAINT CK_QuestionFeedback_label
            CHECK (usefulness_label IS NULL OR usefulness_label IN ('useful', 'less_useful', 'irrelevant'))
    );
    PRINT 'Table QuestionFeedback created.';
END
GO

-- ============================================================
-- TABLE: Q_Responses
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Q_Responses')
BEGIN
    CREATE TABLE Q_Responses (
        response_id     INT IDENTITY(1,1) PRIMARY KEY,
        session_id      INT           NOT NULL REFERENCES Sessions(session_id),
        question_id     INT           NOT NULL REFERENCES Q_Questions(question_id),
        stage_number    INT           NOT NULL,
        response_choice VARCHAR(50)   NOT NULL,
        cal_score       FLOAT         NOT NULL,
        timestamp       DATETIME      NOT NULL DEFAULT GETDATE()
    );
    PRINT 'Table Q_Responses created.';
END
GO


-- ============================================================
-- TABLE: FacialEmotions
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'FacialEmotions')
BEGIN
    CREATE TABLE FacialEmotions (
        emotion_id        INT IDENTITY(1,1) PRIMARY KEY,
        session_id        INT          NOT NULL REFERENCES Sessions(session_id),
        dominant_emotion  VARCHAR(50)  NOT NULL,
        happy             FLOAT        NOT NULL DEFAULT 0.0,
        sad               FLOAT        NOT NULL DEFAULT 0.0,
        angry             FLOAT        NOT NULL DEFAULT 0.0,
        fear              FLOAT        NOT NULL DEFAULT 0.0,
        surprise          FLOAT        NOT NULL DEFAULT 0.0,
        disgust           FLOAT        NOT NULL DEFAULT 0.0,
        neutral           FLOAT        NOT NULL DEFAULT 0.0,
        captured_at       DATETIME     NOT NULL DEFAULT GETDATE(),
        image_path        VARCHAR(260) NULL,   -- saved face image (file name inside emotion_images)
        stage_number      INT          NULL,   -- questionnaire stage when the image was taken
        question_id       INT          NULL,
        CONSTRAINT FK_FacialEmotions_question FOREIGN KEY (question_id) REFERENCES Q_Questions(question_id)
    );
    PRINT 'Table FacialEmotions created.';
END
GO

-- ============================================================
-- TABLE: MH_Results
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'MH_Results')
BEGIN
    CREATE TABLE MH_Results (
        result_id         INT IDENTITY(1,1) PRIMARY KEY,
        session_id        INT          NOT NULL UNIQUE REFERENCES Sessions(session_id),
        user_id           INT          NOT NULL REFERENCES Users(user_id),
        emotional_score   FLOAT        NOT NULL DEFAULT 0.0,
        functional_score  FLOAT        NOT NULL DEFAULT 0.0,
        context_score     FLOAT        NOT NULL DEFAULT 0.0,
        isolation_score   FLOAT        NOT NULL DEFAULT 0.0,
        critical_score    FLOAT        NOT NULL DEFAULT 0.0,
        eeg_avg           FLOAT        NULL,
        avg_pulse         FLOAT        NULL,
        avg_bp_systolic   FLOAT        NULL,
        dominant_emotion  VARCHAR(50)  NULL,
        final_score       FLOAT        NOT NULL,
        risk_class        VARCHAR(50)  NOT NULL
                          CHECK (risk_class IN (
                              'Healthy', 'Mild Stress',
                              'Moderate Risk', 'High Risk', 'Critical Risk'
                          )),
        calculated_at     DATETIME     NOT NULL DEFAULT GETDATE(),
        questionnaire_score FLOAT      NULL,   -- weighted questionnaire score (0-4)
        physio_score        FLOAT      NULL,   -- NULL = no physiological signal was measured
        missing_modalities  VARCHAR(100) NULL  -- comma list (eeg,face,hr,bp); '' = complete; NULL = saved before this check existed
    );
    PRINT 'Table MH_Results created.';
END
GO

-- ============================================================
-- TABLE: Appointments (High / Critical risk -> psychologist booking)
-- ============================================================
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Appointments')
BEGIN
    CREATE TABLE Appointments (
        appointment_id  INT IDENTITY(1,1) PRIMARY KEY,
        student_id      INT         NOT NULL REFERENCES Users(user_id),
        psychologist_id INT         NOT NULL REFERENCES Users(user_id),
        session_id      INT         NOT NULL REFERENCES Sessions(session_id),
        status          VARCHAR(20) NOT NULL DEFAULT 'Scheduled',
        created_at      DATETIME    NOT NULL DEFAULT GETDATE(),
        CONSTRAINT CK_Appointments_status CHECK (status IN ('Scheduled', 'Completed', 'Cancelled'))
    );
    PRINT 'Table Appointments created.';
END
GO

-- One Scheduled appointment per session (stops double booking)
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_Appointments_session_scheduled')
BEGIN
    CREATE UNIQUE INDEX UX_Appointments_session_scheduled
        ON Appointments (session_id) WHERE status = 'Scheduled';
    PRINT 'Index UX_Appointments_session_scheduled created.';
END
GO

-- One feedback row per psychologist and question
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_QuestionFeedback_psychologist_question')
BEGIN
    CREATE UNIQUE INDEX UX_QuestionFeedback_psychologist_question
        ON QuestionFeedback (psychologist_id, question_id);
    PRINT 'Index UX_QuestionFeedback_psychologist_question created.';
END
GO

-- Summary of psychologist feedback per question (read-only helper for reviewing weights)
CREATE OR ALTER VIEW vw_QuestionFeedbackSummary AS
SELECT q.question_id, q.stage_id, q.question_text, q.weight,
       COUNT(f.feedback_id) AS feedback_count,
       AVG(CAST(f.usefulness_score AS FLOAT)) AS avg_score,
       SUM(CASE WHEN f.label = 'useful' THEN 1 ELSE 0 END) AS useful_count,
       SUM(CASE WHEN f.label = 'less_useful' THEN 1 ELSE 0 END) AS less_useful_count,
       SUM(CASE WHEN f.label = 'irrelevant' THEN 1 ELSE 0 END) AS irrelevant_count
FROM Q_Questions q
LEFT JOIN (
    SELECT feedback_id, question_id, usefulness_score,
           COALESCE(usefulness_label,
                    CASE WHEN usefulness_score >= 4 THEN 'useful'
                         WHEN usefulness_score >= 2 THEN 'less_useful'
                         ELSE 'irrelevant' END) AS label
    FROM QuestionFeedback
) f ON f.question_id = q.question_id
GROUP BY q.question_id, q.stage_id, q.question_text, q.weight;
GO

-- ============================================================
-- SEED DATA: Q_Stages (5 stages of the questionnaire)
-- ============================================================
IF NOT EXISTS (SELECT 1 FROM Q_Stages)
BEGIN
    INSERT INTO Q_Stages (stage_number, stage_name, target_role, threshold) VALUES
    (1, 'Emotional State Screening',  'both',  8.0),
    (2, 'Functional Impact',          'both',  8.0),
    (3, 'Contextual Mental Strain',   'both',  8.0),
    (4, 'Psychological Risk',         'both',  8.0),
    (5, 'Critical Risk Screening',    'both',  5.0);
    PRINT 'Q_Stages seed data inserted.';
END
GO

-- ============================================================
-- SEED DATA: Q_Questions (sample questions per stage)
-- ============================================================
IF NOT EXISTS (SELECT 1 FROM Q_Questions)
BEGIN
    -- Stage 1: Emotional State Screening (stage_id = 1)
    INSERT INTO Q_Questions (stage_id, question_text, weight) VALUES
    (1, 'How often do you feel nervous or worried?', 1.0),
    (1, 'How often do you feel sad or down?', 1.0),
    (1, 'How often do everyday tasks feel like too much?', 1.0),
    (1, 'How often do you feel restless or unable to relax?', 1.0),
    (1, 'How often do you feel emotionally worn out?', 1.0),
    (1, 'How often do you worry too much about your responsibilities?', 1.0),
    (1, 'How often do you feel irritable for no clear reason?', 1.0),
    (1, 'How often do you feel like you have no energy to start things?', 1.0),
    (1, 'How often does your mind feel tired or foggy?', 1.0),
    (1, 'How often do you feel scared without knowing why?', 1.0),

    -- Stage 2: Functional Impact (stage_id = 2)
    (2, 'How often does stress make it hard to focus?', 1.0),
    (2, 'How often does stress make you forgetful?', 1.0),
    (2, 'How often do you have trouble sleeping?', 1.0),
    (2, 'How often do you wake up feeling tired?', 1.0),
    (2, 'How often has your eating changed because of stress?', 1.0),
    (2, 'How often have you lost interest in your work or studies?', 1.0),
    (2, 'How often do you feel mentally drained by the end of the day?', 1.0),
    (2, 'How often do you put off tasks because they feel stressful?', 1.0),
    (2, 'How often has your performance at work or school dropped?', 1.0),
    (2, 'How often does stress cause you to avoid people or social situations?', 1.0),

    -- Stage 3: Contextual Mental Strain (stage_id = 3)
    (3, 'How often do deadlines make you anxious?', 1.0),
    (3, 'How often do heavy workloads or long study hours drain you?', 1.0),
    (3, 'How often do exams, evaluations, or performance reviews cause you stress?', 1.0),
    (3, 'How often do you feel pressure from family or institution expectations?', 1.0),
    (3, 'How often do you feel unsupported by peers, managers, or teachers?', 1.0),
    (3, 'How often does comparing yourself to others stress you?', 1.0),
    (3, 'How often do money or job-security concerns affect your peace of mind?', 1.0),
    (3, 'How often do you struggle to balance work/study and personal life?', 1.0),
    (3, 'How often do strict rules, attendance, or schedules make you feel anxious?', 1.0),
    (3, 'How often do you feel your efforts are ignored or not valued?', 1.0),

    -- Stage 4: Psychological Risk (stage_id = 4)
    (4, 'How often do you feel cut off from people around you?', 1.0),
    (4, 'How often do you feel hopeless about your future?', 1.0),
    (4, 'How often do you feel worthless?', 1.0),
    (4, 'How often do you feel emotionally numb or empty?', 1.0),
    (4, 'How often do you feel your problems are too big to handle?', 1.0),
    (4, 'How often do your emotions change quickly and without warning?', 1.0),
    (4, 'How often do you get frustrated very easily?', 1.0),
    (4, 'How often do you feel like giving up on your daily duties?', 1.0),
    (4, 'How often do you avoid meeting or talking to others?', 1.0),
    (4, 'How often do you feel like your life has no purpose?', 1.0),

    -- Stage 5: Critical Risk Screening (stage_id = 5)
    (5, 'Have you had thoughts of hurting yourself?', 2.0),
    (5, 'Have you felt that life is not worth living?', 2.0),
    (5, 'Have you wished you could just disappear?', 2.0),
    (5, 'Have you stopped doing things you used to enjoy?', 1.0),
    (5, 'Have you felt completely trapped in your situation?', 1.5),
    (5, 'Have you felt like a burden to others?', 1.5),
    (5, 'Have you lost interest in taking care of your health or safety?', 1.5),
    (5, 'Have you felt that no one would understand what you are going through?', 1.0),
    (5, 'Have you thought about ending your life, even if you would not act on it?', 2.0),
    (5, 'Have you felt that things will never get better no matter what you do?', 1.5);

    PRINT 'Q_Questions seed data inserted.';
END
GO

-- ============================================================
-- SEED DATA: Pre-registered Users
-- ============================================================
IF NOT EXISTS (SELECT 1 FROM Users WHERE email = 'student@clinic.edu')
BEGIN
    -- Base User (Student)
    -- password is 'password123' (plaintext)
    INSERT INTO Users (name, email, password, role)
    VALUES ('Demo Student', 'student@clinic.edu', 'password123', 'student');
    
    DECLARE @student_user_id INT = SCOPE_IDENTITY();
    
    -- Extended Student Data
    INSERT INTO Students (user_id, cgpa_trend, attendance_drop)
    VALUES (@student_user_id, -0.2, 5.0);
    
    PRINT 'Student seed data inserted.';
END
GO

IF NOT EXISTS (SELECT 1 FROM Users WHERE email = 'teacher@clinic.edu')
BEGIN
    -- Base User (Teacher)
    -- password is 'password123' (plaintext)
    INSERT INTO Users (name, email, password, role)
    VALUES ('Demo Teacher', 'teacher@clinic.edu', 'password123', 'teacher');
    
    DECLARE @teacher_user_id INT = SCOPE_IDENTITY();
    
    -- Extended Teacher Data
    INSERT INTO Teachers (user_id, workload_hrs, class_count)
    VALUES (@teacher_user_id, 24.5, 4);
    
    PRINT 'Teacher seed data inserted.';
END
GO

PRINT '=== VirtualClinicDB schema created successfully ===';
GO

