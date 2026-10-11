"""processing/eeg.py — EEG signal preprocessing and stress index calculation."""

import logging
import numpy as np
from scipy.signal import butter, sosfilt

from processing.scorer import MIN_EEG_SNAPSHOTS

logger = logging.getLogger(__name__)

EEG_SAMPLE_RATE = 256.0  # Muse headset sampling rate (Hz)


def bandpass_filter(data: np.ndarray, lowcut: float, highcut: float,
                    fs: float = EEG_SAMPLE_RATE, order: int = 4) -> np.ndarray:
    """Apply a Butterworth bandpass filter to a 1-D EEG signal."""
    nyquist = 0.5 * fs
    sos = butter(order, [lowcut / nyquist, highcut / nyquist], btype="band", output="sos")
    return sosfilt(sos, data)


def compute_band_power(signal: np.ndarray, fs: float, low: float, high: float) -> float:
    """Compute mean spectral power in a frequency band via FFT."""
    if len(signal) == 0:
        return 0.0
    n = len(signal)
    fft_power = np.abs(np.fft.rfft(signal)) ** 2 / n
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    band_mask = (freqs >= low) & (freqs <= high)
    band = fft_power[band_mask]
    return float(np.mean(band)) if len(band) > 0 else 0.0


def preprocess_eeg(session_id: int, conn):
    """
    Average the real-time EEG summaries saved in EEG_Snapshots for a session.

    Returns None when fewer than MIN_EEG_SNAPSHOTS rows exist (EEG not measured):
    no zeros or made-up values. Otherwise:
        {alpha_power, beta_power, theta_power, stress_index, eeg_score}
    Database errors are not hidden: they propagate to the caller.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*), AVG(alpha_power), AVG(beta_power), AVG(theta_power), AVG(stress_index) "
        "FROM EEG_Snapshots WHERE session_id = ?",
        (session_id,)
    )
    row = cursor.fetchone()
    if row is None or row[0] < MIN_EEG_SNAPSHOTS:
        logger.info("EEG not measured for session %d (%d snapshots).", session_id, row[0] if row else 0)
        return None

    alpha, beta, theta, stress_index = float(row[1]), float(row[2]), float(row[3]), float(row[4])
    eeg_score = min(4.0, stress_index * 0.8)
    logger.info("EEG session %d from %d snapshots: stress=%.4f", session_id, row[0], stress_index)
    return {"alpha_power": round(alpha, 6), "beta_power": round(beta, 6),
            "theta_power": round(theta, 6), "stress_index": round(stress_index, 4),
            "eeg_score": round(eeg_score, 4)}
