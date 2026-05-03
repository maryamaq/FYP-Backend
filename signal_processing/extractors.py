import numpy as np

def extract_eeg_features(samples, fs=256):
    """Expects a list of samples (N, 4). Returns band powers and stress index."""
    if not samples or len(samples) < fs:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    # Average across all 4 channels to create a single signal
    data = np.mean(samples, axis=1)
    n = len(data)
    
    # Compute FFT
    fft_vals = np.abs(np.fft.rfft(data))**2 / n
    freqs = np.fft.rfftfreq(n, d=1.0/fs)

    def get_band_power(low, high):
        mask = (freqs >= low) & (freqs <= high)
        return float(np.mean(fft_vals[mask])) if np.any(mask) else 0.0

    delta = get_band_power(1.0, 4.0)
    theta = get_band_power(4.0, 8.0)
    alpha = get_band_power(8.0, 13.0)
    beta = get_band_power(13.0, 30.0)
    gamma = get_band_power(30.0, 50.0)

    stress_index = (beta + theta) / alpha if alpha > 0 else 0.0
    return delta, theta, alpha, beta, gamma, stress_index


def extract_ppg_hr(samples, fs=64):
    """Rough Heart Rate estimation from PPG using peak frequency."""
    if not samples or len(samples) < fs:
        return 75.0 # Default fallback
    
    # Use channel 0 (ambient/primary PPG signal)
    data = np.array(samples)[:, 0]
    n = len(data)
    
    fft_vals = np.abs(np.fft.rfft(data))**2 / n
    freqs = np.fft.rfftfreq(n, d=1.0/fs)
    
    # Human heart rate typically 0.8 Hz (48 bpm) to 3 Hz (180 bpm)
    mask = (freqs >= 0.8) & (freqs <= 3.0)
    if not np.any(mask):
        return 75.0
        
    dominant_freq = freqs[mask][np.argmax(fft_vals[mask])]
    hr = dominant_freq * 60.0
    return float(hr)
