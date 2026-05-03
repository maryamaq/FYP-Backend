# Multimodal Virtual Clinic — System Guide

## Table of Contents
1. [What the System Does](#1-what-the-system-does)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Database Schema](#4-database-schema)
5. [Folder Structure](#5-folder-structure)
6. [Setup & Running](#6-setup--running)
7. [Session Lifecycle](#7-session-lifecycle)
8. [API Reference](#8-api-reference)
9. [ML Pipeline](#9-ml-pipeline)
10. [Hardware Integration & Processing](#10-hardware-integration--processing)
11. [Scoring Formulas](#11-scoring-formulas)

---

## 1. What the System Does

A university mental health assessment platform. A **student or teacher** opens a mobile/web app, fills out a 5-stage psychological questionnaire, and while answering, three data streams are collected silently:

| Stream | Source | How |
|--------|--------|-----|
| Facial emotion | Device camera (every 5 sec) | Base64 JPEG → Custom CNN / DeepFace fallback |
| EEG + Heart Rate | Muse 2 headset | Bluetooth → muselsl → WindowProcessor (30s) |
| Blood Pressure | BLE BP cuff | Bluetooth BLE → Captured Before & After Session |

When the questionnaire ends, all sources are **fused by an ML model** to output one of:

| ML Label | DB `risk_class` | Meaning |
|----------|-----------------|---------|
| `Normal` | `Healthy` | No action needed |
| `Calm Down` | `Mild Stress` | Suggest breathing/relaxation |
| `See Psychologist` | `High Risk` | Recommend professional help |
| `Emergency` | `Critical Risk` | Immediate intervention required |

Two separate models exist — **one for students, one for teachers** — because their stress factors differ.

---

## 2. System Architecture

```
CLIENT LAYER
  Any frontend (Flutter / React / etc.)
       |
       | REST API (JSON)
       v
BACKEND LAYER — Python FastAPI (port 8000)
  /auth          Login, JWT tokens
  /session       Start/End session, start_with_muse, end_with_muse
  /questionnaire Submit stage answers, get questions
  /sensors       Emotion frames
  /results       Final recommendation + score breakdown
       |
PROCESSING LAYER
  Window Processor (Background Thread)
    Reads 30-second chunks from LSL (EEG/PPG)
    Extracts Band Powers (Alpha, Beta, Theta) + Stress Index
    Computes Heart Rate + Fetch closest Emotion + Questionnaire Score
    Saves features to `WindowAnalysis`
  ML Models
    model_student.pkl  RandomForestClassifier
    model_teacher.pkl  RandomForestClassifier
       |
DATABASE LAYER — Microsoft SQL Server (VirtualClinicDB)
  Users, Students, Teachers, Sessions
  SessionBP, WindowAnalysis, FacialEmotions, EmotionImages
  Q_Stages, Q_Questions, Q_Responses
  MH_Results
```

---

## 3. Technology Stack

### Backend
| Package | Purpose |
|---------|---------|
| `fastapi` | REST API |
| `uvicorn` | ASGI server |
| `pyodbc` | SQL Server connection (ODBC Driver 17) |
| `python-jose[cryptography]` | JWT tokens |
| `pydantic-settings` | Settings from `.env` |

### ML / AI
| Package | Purpose |
|---------|---------|
| `deepface` | Facial emotion detection (pre-trained fallback) |
| `tensorflow` | Custom CNN emotion model |
| `scikit-learn` | RandomForestClassifier for student/teacher models |
| `joblib` | Save/load `.pkl` model files |
| `opencv-python` | Image decode and face detection |
| `numpy` / `scipy` | EEG signal filtering & FFT |

### Hardware & Signal Processing
| Package | Purpose |
|---------|---------|
| `muselsl` | CLI — streams Muse headset via LSL protocol |
| `pylsl` | Python — reads EEG/PPG streams from muselsl |
| `bleak` | Python BLE client — reads BP cuff |

---

## 4. Database Schema

> **To set up:** Run `database/schema.sql` in SSMS, then run `python db_migrations.py`.

### Core Tables

```sql
Users        (user_id PK, name, email, password, role)
             -- role: 'student' | 'teacher' | 'psychologist'
             -- Pre-seeded accounts — no registration endpoint

Students     (student_id PK, user_id FK → Users, cgpa_trend, attendance_drop)

Teachers     (teacher_id PK, user_id FK → Users, workload_hrs, class_count)

Sessions     (session_id PK, user_id FK, start_time, end_time)

SessionBP    (bp_id PK, session_id FK, baseline_sys, baseline_dia, baseline_pulse,
              after_sys, after_dia, after_pulse, delta_sys, delta_dia, delta_pulse)

WindowAnalysis (window_id PK, session_id FK, window_start, window_end, 
                eeg_delta, eeg_theta, eeg_alpha, eeg_beta, eeg_gamma, 
                stress_index, ppg_hr, emotion_distress, questionnaire_score, window_risk)

FacialEmotions (emotion_id PK, session_id FK, dominant_emotion,
                happy, sad, angry, fear, surprise, disgust, neutral,
                captured_at, image_id FK, stage_number)

EmotionImages  (image_id PK, user_id FK, session_id FK,
                stage_number, image_name, captured_at)

Q_Stages     (stage_id PK, stage_number, stage_name, target_role, threshold)

Q_Questions  (question_id PK, stage_id FK, question_text, weight)

Q_Responses  (response_id PK, session_id FK, question_id FK,
              stage_number, response_choice, cal_score, timestamp)
```

---

## 5. Folder Structure

```
Backend/
├── main.py                    App entry point, router registration, startup/shutdown
├── config.py                  All settings (DB, JWT, paths, BASE_DIR)
├── database.py                get_connection(), test_connection(), db_cursor()
├── db_migrations.py           Idempotent schema migrations (safe to re-run)
├── start_server.ps1           Windows launcher — prints LAN IP, starts uvicorn
├── requirements.txt
├── test_endpoints.py          API integration test suite
│
├── models/                    Pydantic request/response schemas
│
├── routers/                   FastAPI route handlers
│   ├── auth.py                POST /auth/login
│   ├── sessions.py            POST /session/start, start_with_muse, end_with_muse
│   ├── questionnaire.py       POST /questionnaire/submit; GET /questionnaire/...
│   ├── sensors.py             POST /sensors/emotion
│   └── results.py             GET /results/{session_id}, /results/all
│
├── signal_processing/
│   ├── lsl_stream.py          Starts/Stops muselsl process and resolves pylsl streams
│   ├── extractors.py          FFT functions for EEG band powers and PPG heart rate
│   ├── window_processor.py    Background thread: pools 30s data, extracts, saves to DB
│   └── callbacks.py           Fetches recent emotion/questionnaire scores for WindowProcessor
│
├── hardware/
│   └── bp_reader.py           bleak BLE reader for BP cuff
│
├── database/
│   └── schema.sql              Full SQL Server schema — run this first in SSMS
```

---

## 6. Setup & Running

(Standard Python virtual environment setup, install requirements, set up SQL Server, and run `.\start_server.ps1`)

---

## 7. Session Lifecycle

```
1. User opens app
   → POST /auth/login { email, password }
   ← { access_token, user_id, role }

2. App starts a session (Hardware flow)
   → POST /session/{session_id}/start_with_muse
     a. Starts LSL streams (EEG/PPG)
     b. Takes Baseline BP from cuff (saves to SessionBP)
     c. Starts 30-Second WindowProcessor thread
   ← { message: "started" }

3. Parallel data streams:
   📷 Camera loop (every 5 seconds)
      App captures frame → POST /sensors/emotion
      Server: Custom CNN / DeepFace → INSERT FacialEmotions

   🧠 WindowProcessor (Background)
      Every 30s → Pulls EEG/PPG chunk → FFT → Extracts features + Stress Index
      → INSERT WindowAnalysis

4. Questionnaire (4 active stages)
   GET /questionnaire/questions/{stage_number}
   User answers → POST /questionnaire/submit { session_id, stage_number, answers[] }

5. App ends the session
   → POST /session/{session_id}/end_with_muse
     a. Stops WindowProcessor and LSL stream
     b. Takes After-session BP → computes deltas → Updates SessionBP
     c. Computes final ML prediction
     d. INSERT MH_Results
   ← { recommendation, final_score, confidence }
```

---

## 8. API Reference

### Sessions (Hardware Integration)
```
POST /session/{session_id}/start_with_muse
→  Starts LSL, takes Baseline BP, spins up WindowProcessor thread.

POST /session/{session_id}/end_with_muse
→  Stops LSL, takes After BP, calculates Deltas, stops WindowProcessor.
```

*(Authentication, Questionnaire, Results endpoints remain the same REST JSON patterns)*

---

## 9. Hardware Integration & Processing

### Signal Processing (30-Second Windows)
We do **not** store raw EEG/PPG in the database (256 Hz would bloat the DB). Instead:
1. `muselsl stream --ppg` runs continuously.
2. `WindowProcessor` sleeps for 30s, then pulls the entire chunk via `pylsl`.
3. `extractors.py` averages channels, runs a Fast Fourier Transform (FFT).
4. Delta, Theta, Alpha, Beta, Gamma powers are saved to `WindowAnalysis`.
5. `Stress Index = (Beta + Theta) / Alpha` is computed live.
6. Heart Rate is approximated from PPG channel peak frequency.

### BLE Blood Pressure Cuff
- Uses standard GATT UUID: `00002a35-0000-1000-8000-00805f9b34fb`.
- Reads only twice: **Baseline** (before session) and **After** (post session).
- Stores Deltas (`delta_sys`, `delta_dia`) in `SessionBP`.

---

## 10. Scoring Formulas

### Dynamic Emotion Multiplier
When a user submits an answer, the scorer finds the closest camera frame captured within 60 seconds. The base score is multiplied:
- Happy: 0.7×
- Fear/Sad: 1.4×
- Angry: 1.5×

### Window Risk Calculation
Inside the `WindowProcessor`, a live 30-second risk score is computed:
`window_risk = 0.4 * questionnaire_score + 0.2 * stress_index + 0.2 * (systolic/200) + 0.2 * emotion_distress`

At the end of the session, the ML pipeline can either take the `MAX(window_risk)` or use the statistical average of all windows as input features for the RandomForest model.
