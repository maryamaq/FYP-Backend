# ============================================================
# signal_processing/window_processor.py — Real-time Hardware Integration
#
# This is the core engine for hardware data collection. 
# It runs a background thread that wakes up every 30 seconds to:
#  1. Pull exactly 30 seconds of accumulated EEG/PPG chunks from LSL
#  2. Extract Alpha, Beta, Theta, Delta, Gamma frequency powers
#  3. Compute an EEG stress_index and a PPG heart rate
#  4. Fetch the latest Facial Emotion and Questionnaire score
#  5. Calculate a composite `window_risk` and save ONE row to WindowAnalysis
# ============================================================

import threading
import time
import logging
from datetime import datetime, timezone
from database import get_connection
from signal_processing.extractors import extract_eeg_features, extract_ppg_hr

logger = logging.getLogger(__name__)

class WindowProcessor:
    def __init__(self, session_id, lsl_manager, baseline_sys, callbacks):
        self.session_id = session_id
        self.lsl = lsl_manager
        self.baseline_sys = baseline_sys
        self.callbacks = callbacks # dict with functions
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=35)

    def _run_loop(self):
        # Empty old buffers before starting the first window
        if self.lsl.eeg_inlet: self.lsl.eeg_inlet.pull_chunk()
        if self.lsl.ppg_inlet: self.lsl.ppg_inlet.pull_chunk()

        while self.running:
            window_start = datetime.now(timezone.utc)
            
            # Sleep 30 seconds to let LSL buffer fill up
            for _ in range(30):
                if not self.running: return
                time.sleep(1)

            window_end = datetime.now(timezone.utc)

            # 1. Pull Data Chunks
            eeg_chunk, _ = self.lsl.eeg_inlet.pull_chunk() if self.lsl.eeg_inlet else ([], [])
            ppg_chunk, _ = self.lsl.ppg_inlet.pull_chunk() if self.lsl.ppg_inlet else ([], [])

            # 2. Extract Features
            delta, theta, alpha, beta, gamma, stress_idx = extract_eeg_features(eeg_chunk)
            hr = extract_ppg_hr(ppg_chunk)

            # 3. Fetch Callbacks (Emotion + Questionnaire)
            emotion_distress = self.callbacks["get_emotion"](self.session_id, window_end)
            q_score = self.callbacks["get_q_score"](self.session_id)

            # 4. Calculate Risk
            window_risk = (0.4 * q_score) + (0.2 * stress_idx) + (0.2 * (self.baseline_sys / 200.0)) + (0.2 * emotion_distress)

            # 5. Save ONLY features to Database
            self._save_to_db(window_start, window_end, delta, theta, alpha, beta, gamma, stress_idx, hr, emotion_distress, q_score, window_risk)

    def _save_to_db(self, start, end, d, t, a, b, g, stress, hr, emotion, q_score, risk):
        conn = get_connection()
        try:
            conn.cursor().execute("""
                INSERT INTO WindowAnalysis 
                (session_id, window_start, window_end, eeg_delta, eeg_theta, eeg_alpha, 
                 eeg_beta, eeg_gamma, stress_index, ppg_hr, emotion_distress, questionnaire_score, window_risk)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (self.session_id, start, end, d, t, a, b, g, stress, hr, emotion, q_score, risk))
            conn.commit()
            logger.info(f"Saved 30s window for session {self.session_id}. Risk: {risk:.3f}")
        except Exception as e:
            logger.error(f"Failed to save window: {e}")
        finally:
            conn.close()
