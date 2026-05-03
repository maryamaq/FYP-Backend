import subprocess
import sys
import time
import logging
from pylsl import resolve_byprop, StreamInlet

logger = logging.getLogger(__name__)

class LSLManager:
    def __init__(self):
        self.proc = None
        self.eeg_inlet = None
        self.ppg_inlet = None

    def start_stream(self):
        if self.proc is not None:
            return True # Already running

        logger.info("Starting muselsl stream subprocess...")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "muselsl", "stream", "--ppg"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(8) # Wait for Bluetooth connection and LSL broadcast

        # Resolve streams
        eeg_streams = resolve_byprop("type", "EEG", timeout=5)
        ppg_streams = resolve_byprop("type", "PPG", timeout=5)

        if not eeg_streams or not ppg_streams:
            self.stop_stream()
            raise RuntimeError("EEG or PPG stream not found. Is the Muse headset paired?")

        self.eeg_inlet = StreamInlet(eeg_streams[0])
        self.ppg_inlet = StreamInlet(ppg_streams[0])
        return True

    def stop_stream(self):
        if self.eeg_inlet:
            self.eeg_inlet.close_stream()
            self.eeg_inlet = None
        if self.ppg_inlet:
            self.ppg_inlet.close_stream()
            self.ppg_inlet = None
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            self.proc = None

# Global instance
lsl_manager = LSLManager()
