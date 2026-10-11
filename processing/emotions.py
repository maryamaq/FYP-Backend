"""processing/emotions.py — Facial emotion aggregation and distress scoring."""

import logging
from collections import Counter

from processing.scorer import MIN_FACE_SAMPLES

logger = logging.getLogger(__name__)

# Distress map: 0.0 = no distress, 1.0 = maximum distress
DISTRESS_MAP = {
    "happy": 0.0, "neutral": 0.1, "surprise": 0.2,
    "disgust": 0.5, "sad": 0.7, "fear": 0.8,
    "angry": 0.8, "undetected": 0.3,
}

EMOTION_COLUMNS = ("happy", "sad", "angry", "fear", "surprise", "disgust", "neutral")


def preprocess_emotions(session_id: int, conn):
    """
    Aggregate the usable FacialEmotions rows of a session.

    A row is usable when a face was detected: the label is not 'undetected' and the
    seven emotion scores are not all 0 (old rows saved by the previous fallback).

    Returns None when fewer than MIN_FACE_SAMPLES usable rows exist (face not measured).
    Otherwise:
        {dominant_emotion, face_distress, face_score}
        face_distress = mean of DISTRESS_MAP values across the usable captures
        face_score = face_distress * 4   (normalized to 0-4 scale)
    Database errors are not hidden: they propagate to the caller.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT dominant_emotion, happy, sad, angry, fear, surprise, disgust, neutral "
        "FROM FacialEmotions WHERE session_id = ? ORDER BY captured_at ASC", (session_id,)
    )
    labels = []
    for row in cursor.fetchall():
        label = (row.dominant_emotion or "").lower()
        scores = [getattr(row, col) or 0.0 for col in EMOTION_COLUMNS]
        if label == "" or label == "undetected" or not any(scores):
            continue
        labels.append(label)

    if len(labels) < MIN_FACE_SAMPLES:
        logger.info("Face not measured for session %d (%d usable captures).", session_id, len(labels))
        return None

    distress_values = [DISTRESS_MAP.get(lbl, 0.1) for lbl in labels]
    face_distress = sum(distress_values) / len(distress_values)
    counts = Counter(labels)
    dominant = max(counts, key=counts.get)

    logger.info("Emotions session %d: usable=%d distress=%.3f", session_id, len(labels), face_distress)
    return {"dominant_emotion": dominant,
            "face_distress": round(face_distress, 4),
            "face_score": round(face_distress * 4.0, 4)}
