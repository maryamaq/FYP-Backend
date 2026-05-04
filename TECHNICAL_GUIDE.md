# Multimodal Virtual Clinic — Technical Deep Dive & File Mapping

> A complete explanation of every layer of the FastAPI backend: what we built, exactly which files handle the logic, and how each piece works internally.

---

## 1. Backend File Structure (Where is everything?)

To master your Viva, you must know exactly which Python file controls which part of the backend. If an examiner asks to see a specific logic block, open these files:

### 🚀 `main.py` (The Entry Point)
*   **What it does:** This is the heart of the server. It configures the FastAPI application, sets up CORS (so Flutter can talk to it), and mounts the `routers/`. It also uses a `@asynccontextmanager` lifespan event to trigger `ml/predictor.py` to load the `.pkl` Machine Learning models into RAM the moment the server boots up.

### 🌐 `routers/` (The API Endpoints)
*   **`routers/auth.py`**: Handles user login. Generates and validates the JWT tokens.
*   **`routers/sessions.py`**: Handles `/session/start` and `/session/end`. When a session starts, this file is responsible for spawning the background `WindowProcessor` thread. When a session ends, it commands the ML pipeline to generate a final result.
*   **`routers/sensors.py`**: Receives all raw data payloads from Flutter via POST requests. **This file specifically holds the logic for taking the Base64 image, decoding it via OpenCV, and running the Convolutional Neural Network (CNN) emotion analysis.**
*   **`routers/questionnaire.py`**: Receives user answers for the clinical stages and saves them to `Q_Responses`.

### 🧠 `ml/` (Machine Learning Pipeline)
*   **`ml/trainer.py`**: The script used to train the Random Forest / Gradient Boosting models using historical data. It saves the results as `.pkl` files.
*   **`ml/predictor.py`**: Loads `model_student.pkl` and `model_teacher.pkl` into memory. Takes a 16-element feature vector and runs `.predict()` to classify the user (e.g., "Normal", "Calm Down", "Emergency").
*   **`ml/feature_builder.py`**: The "Data Assembler". When a session ends, this file queries `WindowAnalysis`, `SessionBP`, `FacialEmotions`, and `Q_Responses` and builds the exact 16-element float array required by the `predictor.py`.

### 📡 `signal_processing/` (Hardware Integration)
*   **`signal_processing/window_processor.py`**: The core of the real-time hardware fusion. It runs an infinite loop in a background thread that sleeps for exactly 30 seconds, wakes up, pulls the LSL (Lab Streaming Layer) buffer, and saves a summarized row to the database.
*   **`signal_processing/extractors.py`**: Contains the mathematical formulas. It runs the FFT (Fast Fourier Transform) on the raw EEG arrays to isolate Alpha, Beta, Theta, Delta, and Gamma wave powers.

### 🧮 `scoring/` (Mathematical Fallbacks)
*   **`scoring/questionnaire_scorer.py`**: Takes raw answers (0-4) and converts them into the 5 clinical component scores (Emotional distress, Functional impairment, etc.).
*   **`scoring/risk_engine.py`**: A fallback ruleset. If the `.pkl` ML models ever fail to load, this file contains hardcoded mathematical weights to still generate a basic risk score.

---

## 2. Deep Dive: How the Pipeline Actually Works

If the examiner asks: *"Explain exactly what happens when the user clicks 'Start Session' until they get their result,"* you can give this step-by-step breakdown:

### Step 1: Session Initiation (`routers/sessions.py`)
1. Flutter hits `/session/start`.
2. The server creates a new entry in the `Sessions` table.
3. It stores the baseline Blood Pressure reading in the `SessionBP` table.
4. **Crucial Step:** It creates a `WindowProcessor` Python object and calls `.start()`, which spins up a dedicated background thread for this specific user.

### Step 2: Real-time Windowing (`signal_processing/window_processor.py`)
While the user is answering the questionnaire on their phone, the background thread is running:
1. It sleeps for 30 seconds, letting the `muselsl` hardware buffers fill up.
2. It wakes up and pulls the 30 seconds of raw EEG and PPG data using `pylsl.pull_chunk()`.
3. **The Mathematics (How we compress 7,680 rows into 1 row):** It passes the raw array to `extractors.py`. In 30 seconds at 256Hz, the Muse collects 7,680 raw voltage readings per channel. Instead of saving raw voltages (the Time Domain), we use **NumPy's FFT (Fast Fourier Transform)** to convert the data into the **Frequency Domain**. 
   - FFT reveals the "Power Spectral Density"—showing how much energy is in specific brainwave frequencies.
   - We extract just 5 numbers: Delta (1-4Hz), Theta (4-8Hz), Alpha (8-13Hz), Beta (13-30Hz), and Gamma (30-50Hz).
   - From this, we calculate a single mathematical `stress_index = (Beta + Theta) / Alpha` and use FFT again to find the peak `ppg_hr` (Heart Rate).
4. It queries the database for the most recent distress score logged by the camera.
5. It `INSERT`s exactly one summarized row into the `WindowAnalysis` table.

### Step 3: Facial Emotion Capture (`routers/sensors.py`)
Every 5 seconds, Flutter sends a Base64 string to `/sensors/emotion`.
1. The endpoint decodes it into a binary NumPy array and reads it with `cv2.imdecode`.
2. It runs OpenCV Haar Cascades to find the bounding box of the face.
3. It passes the cropped face to our custom `custom_emotion_model.h5` CNN.
4. If the CNN is confident (> 55%), it returns the dominant emotion. If it is unsure, it falls back to the `DeepFace` library.
5. It saves the emotion confidence percentages to the `FacialEmotions` table.

### Step 4: Final Prediction (`ml/feature_builder.py` -> `ml/predictor.py`)
1. Flutter hits `/session/end`.
2. The backend stops the `WindowProcessor` thread.
3. `routers/sessions.py` calls `feature_builder.py`.
4. The Feature Builder queries the `WindowAnalysis` table, calculates the *average* EEG Stress Index across the whole session, calculates the BP deltas, and retrieves the questionnaire sums. It formats this into a strict 16-item array `[2.0, 0.4, 24.5, ...]`.
5. It passes the array to `predictor.py`. The loaded Sci-Kit Learn model returns `[Prediction: "See Psychologist", Confidence: 87.5%]`.
6. This final state is saved to `MH_Results` and returned to Flutter.

---

## 3. The Architecture Decision: Why 30-Second Windows?

### The Problem:
The Muse headset streams EEG at **256 samples per second** (256 Hz). If a session takes 5 minutes, that is `256 * 60 * 5 = 76,800` rows of raw data for just ONE sensor. Saving this directly to SQL Server in real-time creates massive network bottlenecks and instantly bloats the database, crashing the server if multiple users log in.

### Our Solution:
Instead of raw storage, we moved to **Edge Computing / Feature-Level Late Fusion**. We let the LSL buffer accumulate in RAM. Every 30 seconds, `window_processor.py` analyzes the RAM buffer, extracts the specific frequencies we care about, and saves a **single summarized row**. 
A 5-minute session now generates exactly **10 rows** in the `WindowAnalysis` table instead of 76,800 rows, making our backend infinitely more scalable and incredibly fast.
