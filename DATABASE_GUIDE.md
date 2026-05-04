# Database Guide — Multimodal Virtual Clinic

This document explains the schema and purpose of each table in the Microsoft SQL Server database (`VirtualClinicDB`), reflecting the exact state of `schema.sql`.

## 1. User & Role Management
*   **`Users`**: The central auth table containing `user_id`, `name`, `email`, `password` (plaintext for demo purposes), and `role` (`student`, `teacher`, `psychologist`).
*   **`Students`**: Role-specific extension table holding academic metrics: `cgpa_trend` (negative means declining) and `attendance_drop` (positive means more absences).
*   **`Teachers`**: Role-specific extension table holding workload metrics: `workload_hrs` and `class_count`.

## 2. Session Tracking
*   **`Sessions`**: The core tracking entity. Every time a user takes a test, a new `session_id` is created with a `start_time` and `end_time`. All subsequent data is linked to this `session_id`. Status is either `active` or `completed`.

## 3. Hardware Data (The 30-Second Approach)
We explicitly avoid saving raw sensor data (e.g., thousands of EEG points per second) to prevent database bloat. Instead, we use aggregated windows and event-based logging.
*   **`SessionBP`**: Tracks Blood Pressure from the BLE cuff. It records a `baseline` (before the test), an `after` (post-test), and the `delta` (difference) for systolic, diastolic, and pulse rate.
*   **`WindowAnalysis`**: This is the heart of the hardware integration. Every 30 seconds, the background thread extracts frequency powers (`eeg_alpha`, `eeg_beta`, `eeg_theta`, `eeg_delta`, `eeg_gamma`) from the EEG buffer, computes a `stress_index`, gets heart rate from PPG (`ppg_hr`), and fuses it with the latest emotion and questionnaire scores into a `window_risk`. This table holds one summarized row per 30 seconds.

## 4. Facial Emotion & Computer Vision
*   **`FacialEmotions`**: Holds the AI-predicted result for facial images captured during the session. Contains the `dominant_emotion` and the exact confidence percentages for all 7 emotion classes (happy, sad, angry, fear, surprise, disgust, neutral).

## 5. Psychological Questionnaire
*   **`Q_Stages`**: Defines the 5 distinct stages of the assessment (e.g., Emotional State Screening, Functional Impact) and the `threshold` score required to pass to the next stage.
*   **`Q_Questions`**: The actual questions (10 per stage) and their respective clinical `weight`.
*   **`Q_Responses`**: Records every answer the user selects, the stage they were in, the textual `response_choice`, and the `cal_score` (calculated score).

## 6. Final Results
*   **`MH_Results`**: At the end of the session, the ML pipeline processes all the aggregate data and writes the final verdict here. It holds the summary scores for all 5 stages (`emotional_score`, `functional_score`, etc.), the overall sensor averages (`eeg_avg`, `avg_pulse`, `avg_bp_systolic`), the `final_score`, and the ML `risk_class` (e.g., "Healthy", "Critical Risk"). This table populates the Psychologist Dashboard.
