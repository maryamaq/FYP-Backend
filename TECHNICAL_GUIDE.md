# Multimodal Virtual Clinic — Technical Deep Dive

> A complete explanation of every layer of the backend: what we built, why we chose each technology, and how each piece works internally.

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [Why FastAPI?](#2-why-fastapi)
3. [Database Layer](#3-database-layer)
4. [Hardware Integration — 30-Second Window Processing](#4-hardware-integration--30-second-window-processing)
5. [Facial Emotion Detection — Dual Model System](#5-facial-emotion-detection--dual-model-system)
6. [ML Pipeline — Feature Building & Prediction](#6-ml-pipeline--feature-building--prediction)

---

## 1. Project Overview
This is the backend of the **Multimodal Virtual Clinic** — a Final Year Project that assesses the mental health of university students and teachers. Instead of relying on a single test, it fuses four data sources simultaneously: Questionnaire, Webcam (Facial Emotions), Muse EEG Headset, and BLE BP Cuff.

All four streams are aggregated into summarized chunks and evaluated by a **RandomForest ML model**.

---

## 2. Why FastAPI?
- **Automatic Data Validation:** Pydantic models automatically reject invalid types.
- **Built-in Docs:** Swagger UI at `/docs`.
- **ASGI + Async:** Handles blocking hardware I/O (like reading BLE devices or LSL streams) effectively without freezing the whole web server.

---

## 3. Database Layer
We use **Microsoft SQL Server** with **pyodbc**. 
- Pre-seeded users (Students/Teachers).
- `SessionBP`: Captures only baseline and after-session readings to calculate Deltas.
- `WindowAnalysis`: Replaces raw `SensorData`. We don't save 256Hz EEG. We extract features every 30 seconds and save a single row per window.

---

## 4. Hardware Integration — 30-Second Window Processing

### The Challenge: High-Frequency Data
The Muse headset streams EEG at **256 samples per second** (256 Hz). Saving this to SQL Server in real-time is inefficient and bloats the database.

### The Solution: `WindowProcessor`
In the new architecture, we use a **Feature-Level Late Fusion** approach in real-time.
1. `muselsl stream --ppg` broadcasts the raw data to the local network.
2. A background thread (`WindowProcessor`) wakes up every 30 seconds.
3. It consumes the LSL buffer via `pylsl.pull_chunk()`.
4. It calls `extractors.py` which applies an **FFT (Fast Fourier Transform)** to extract:
   - Delta, Theta, Alpha, Beta, Gamma band powers.
   - `stress_index = (Beta + Theta) / Alpha`.
   - `ppg_hr` (Peak frequency from the PPG channel).
5. It then queries the DB for the closest facial emotion distress and the current cumulative questionnaire score.
6. It computes a unified `window_risk` and saves a single row to the `WindowAnalysis` table.

### Blood Pressure
The Omron BP Cuff uses standard Bluetooth LE GATT (`0x2A35`). Instead of continuous monitoring, the API captures **Baseline BP** when the session starts, and **After-session BP** when it ends, storing the difference in `SessionBP`.

---

## 5. Facial Emotion Detection — Dual Model System
1. **Custom CNN** — Trained on FER-2013, 48×48 grayscale. Used if confidence > 55%.
2. **DeepFace** — Fallback if custom model fails.

*Dynamic Emotion Multiplier:* Questionnaire answers are timestamp-matched to camera frames. Answering "I feel fine" while showing Fear multiplies the risk score by 1.4x.

---

## 6. ML Pipeline — Feature Building & Prediction
The ML models (`model_student.pkl`, `model_teacher.pkl`) are RandomForestClassifiers. 

Because we now use 30-second windows instead of raw data, the final session prediction takes the `AVG()` of all windows in `WindowAnalysis` to build the feature vector, or alternatively relies on a simple `MAX(window_risk)` threshold to determine if the user is in an Emergency state.
