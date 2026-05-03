# Database Guide — Multimodal Virtual Clinic

This document explains the schema and purpose of each table in the Microsoft SQL Server database.

## 1. User & Role Management
*   **`Users`**: The central auth table containing `user_id`, `email`, `password` (plaintext for demo purposes), and `role` (`student`, `teacher`, `psychologist`).
*   **`Students` / `Teachers`**: Role-specific extension tables. 
    *   `Students` holds academic metrics like `cgpa_trend` and `attendance_drop`.
    *   `Teachers` holds workload metrics like `workload_hrs` and `class_count`.

## 2. Session Tracking
*   **`Sessions`**: The core tracking entity. Every time a user takes a test, a new `session_id` is created with a `start_time` and `end_time`. All subsequent data is linked to this `session_id`.

## 3. Hardware Data (The 30-Second Approach)
We explicitly avoid saving raw sensor data to prevent database bloat.
*   **`SessionBP`**: Tracks Blood Pressure from the BLE cuff. It records a `baseline` (before the test), an `after` (post-test), and the `delta` (difference).
*   **`WindowAnalysis`**: This is the heart of the hardware integration. Every 30 seconds, the background thread extracts frequency powers (Alpha, Beta, Theta) from the EEG buffer, computes a `stress_index`, gets heart rate from PPG, and fuses it with the latest emotion and questionnaire scores into a `window_risk`. This table holds one summarized row per 30 seconds.

## 4. Facial Emotion & Computer Vision
*   **`EmotionImages`**: Logs the physical location/filename of the 5-second interval snapshots taken during the test.
*   **`FacialEmotions`**: Holds the AI-predicted result for each image. Contains a `dominant_emotion` and the exact confidence percentage for all 7 emotion classes (happy, sad, angry, etc.).

## 5. Psychological Questionnaire
*   **`Q_Stages`**: Defines the 5 distinct stages of the assessment (e.g., Emotional State, Functional Impact).
*   **`Q_Questions`**: The actual questions and their respective clinical `weight`.
*   **`Q_Responses`**: Records every answer the user selects, the stage they were in, and the `cal_score` (calculated score after applying the emotion distress multiplier).

## 6. Final Results
*   **`MH_Results`**: At the end of the session, the ML pipeline processes all the aggregate data and writes the final verdict here. It holds the summary scores for all 5 stages, the `final_score`, the ML `risk_class` (e.g., "See Psychologist"), and is used to populate the Psychologist Dashboard.
