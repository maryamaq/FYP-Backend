"""processing/scorer.py — Mental health scoring pipeline.

Implements the two-track scoring system:
  1. Questionnaire score (q_score)  — weighted stage scores + context data
  2. Physiological score (physio)   — EEG + face + HR + BP
  3. Final fusion: 0.70 * q_score + 0.30 * physio
  4. Classification into 4 recommendation levels
  5. Safety override for Stage 5 critical answers
"""

import logging

logger = logging.getLogger(__name__)

# ── Rule for signals that were not measured ───────────────────
# A physiological signal with too little data is left out (never replaced by 0
# or a made-up value). The remaining physio weights are rescaled to add up to 1.
# If NO physiological signal was measured: final = NO_PHYSIO_Q_WEIGHT * q_score.
# (Set it to 1.0 to score on the questionnaire alone in that case.)
NO_PHYSIO_Q_WEIGHT = 0.70

# Minimum amount of real data before a signal counts as "measured"
MIN_EEG_SNAPSHOTS = 5      # about 10 seconds of EEG
MIN_FACE_SAMPLES = 3       # face images with a detected face
MIN_HR_READINGS = 3        # PPG pulse readings
MIN_BP_READINGS = 2        # two systolic readings are needed for a change
HR_MIN_BPM = 40            # pulse values outside 40-200 are not real readings
HR_MAX_BPM = 200

# Physiological weights (same numbers as calc_physio_score)
PHYSIO_WEIGHTS = {"eeg": 0.40, "face": 0.25, "hr": 0.20, "bp": 0.15}


# ── Stage score normalization ──────────────────────────────────

def normalize_stage(raw_sum: float, n_questions: int) -> float:
    """Normalize a raw stage score to the 0-4 scale."""
    if n_questions <= 0:
        return 0.0
    return min(4.0, max(0.0, (raw_sum / (n_questions * 4)) * 4))


def get_stage_scores(session_id: int, conn) -> dict:
    """Pull questionnaire responses and compute normalized scores per stage."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT stage_number, SUM(cal_score) AS raw_sum, COUNT(*) AS n "
        "FROM Q_Responses WHERE session_id = ? GROUP BY stage_number",
        (session_id,)
    )
    scores = {}
    for row in cursor.fetchall():
        stage = int(row.stage_number)
        scores[stage] = normalize_stage(float(row.raw_sum or 0), int(row.n))
    return scores


# ── Questionnaire scoring formulas ─────────────────────────────

# Psychologist feedback (QuestionFeedback) is only stored for human review.
# It never changes these weights.

def calc_student_score(stages: dict, cgpa_trend: float = 0.0,
                       attendance_drop: float = 0.0,
                       failed_courses: int = 0, total_courses: int = 1,
                       weights: dict = None) -> float:
    """Compute weighted questionnaire score for a student (0-4 scale)."""
    w = weights or {1: 0.30, 2: 0.20, 3: 0.10, 4: 0.15, 5: 0.05}
    s1 = stages.get(1, 0.0)
    s2 = stages.get(2, 0.0)
    s3 = stages.get(3, 0.0)
    s4 = stages.get(4, 0.0)
    s5 = stages.get(5, 0.0)

    cgpa_score = min(4.0, max(0.0, -cgpa_trend) * 2)
    attend_score = min(4.0, max(0.0, attendance_drop * 0.4))
    fail_ratio = failed_courses / max(total_courses, 1)
    perf_score = min(4.0, fail_ratio * 4)

    stage_total = w[1]*s1 + w[2]*s2 + w[3]*s3 + w[4]*s4 + w[5]*s5
    context_total = 0.10*cgpa_score + 0.05*attend_score + 0.05*perf_score

    return round(min(4.0, max(0.0, stage_total + context_total)), 4)


def calc_teacher_score(stages: dict, course_load: float = 0.0,
                       feedback_trend: float = 0.0) -> float:
    """Compute weighted questionnaire score for a teacher (0-4 scale)."""
    s1 = stages.get(1, 0.0)
    s2 = stages.get(2, 0.0)
    s3 = stages.get(3, 0.0)
    s4 = stages.get(4, 0.0)
    s5 = stages.get(5, 0.0)

    load_score = min(4.0, (course_load / 5.0) * 4)
    feedback_score = min(4.0, max(0.0, -feedback_trend) * 2)

    return round(min(4.0, max(0.0,
        0.30 * s1 + 0.20 * s2 + 0.15 * s3 + 0.15 * s4 +
        0.10 * load_score + 0.05 * feedback_score + 0.05 * s5
    )), 4)


# ── Physiological scoring ──────────────────────────────────────

def calc_physio_score(eeg_score: float = 0.0, face_score: float = 0.0,
                     hr_score: float = 0.0, bp_score: float = 0.0) -> float:
    """Combine physiological signals into a single score (0-4 scale).

    Weights: EEG 40%, Face 25%, HR 20%, BP 15%.
    Missing signals default to 0 — formula still runs.
    """
    return round(min(4.0, max(0.0,
        0.40 * eeg_score + 0.25 * face_score +
        0.20 * hr_score + 0.15 * bp_score
    )), 4)


# ── Final fusion and classification ────────────────────────────

def fuse_scores(q_score: float, physio_score: float) -> float:
    """Fuse questionnaire and physiological scores. 70/30 split."""
    return round(0.70 * q_score + 0.30 * physio_score, 4)


def hr_score(avg_hr: float) -> float:
    """Heart-rate stress score (0-4): 0 at 72 bpm, +1 per 10 bpm above."""
    return min(4.0, max(0.0, (avg_hr - 72.0) / 10.0))


def bp_score(systolic_delta: float) -> float:
    """Blood-pressure stress score (0-4): +1 per 10 mmHg rise in systolic."""
    return min(4.0, max(0.0, systolic_delta / 10.0))


def get_heart_rate(session_id: int, conn):
    """Average pulse from real PPG readings (40-200 bpm), or None if fewer than MIN_HR_READINGS."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS n, AVG(CAST(pulse_rate AS FLOAT)) AS avg_hr FROM SensorData "
        "WHERE session_id = ? AND data_type = 'ppg' AND pulse_rate BETWEEN ? AND ?",
        (session_id, HR_MIN_BPM, HR_MAX_BPM)
    )
    row = cursor.fetchone()
    if row is None or row.n < MIN_HR_READINGS:
        return None
    return float(row.avg_hr)


def get_bp_change(session_id: int, conn):
    """Systolic readings of a session as {first_systolic, delta}, or None if fewer than MIN_BP_READINGS."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT bp_systolic FROM SensorData "
        "WHERE session_id = ? AND data_type = 'bp' AND bp_systolic IS NOT NULL "
        "ORDER BY recorded_at ASC, sensor_id ASC",
        (session_id,)
    )
    rows = cursor.fetchall()
    if len(rows) < MIN_BP_READINGS:
        return None
    first = int(rows[0].bp_systolic)
    last = int(rows[-1].bp_systolic)
    return {"first_systolic": first, "delta": last - first}


def fuse_with_missing(q_score: float, signals: dict) -> dict:
    """Final score when some physiological signals may be missing.

    signals = {"eeg": score or None, "face": ..., "hr": ..., "bp": ...} (0-4 scores).
    A signal that is None was not measured: it is left out and the others are
    rescaled. With all four present this gives the same result as
    fuse_scores(q_score, calc_physio_score(...)).
    Returns {"physio": float or None, "final": float, "missing_modalities": [names]}.
    """
    available = {name: score for name, score in signals.items() if score is not None}
    missing = [name for name in PHYSIO_WEIGHTS if name not in available]
    if not available:
        return {"physio": None, "final": round(NO_PHYSIO_Q_WEIGHT * q_score, 4),
                "missing_modalities": missing}
    weight_sum = sum(PHYSIO_WEIGHTS[name] for name in available)
    physio = sum(PHYSIO_WEIGHTS[name] * available[name] for name in available) / weight_sum
    physio = round(min(4.0, max(0.0, physio)), 4)
    return {"physio": physio, "final": fuse_scores(q_score, physio), "missing_modalities": missing}


def classify(final_score: float) -> str:
    """Map final score to a recommendation label."""
    if final_score <= 1.0:
        return "Normal"
    elif final_score <= 2.0:
        return "Calm Down"
    elif final_score <= 3.0:
        return "See Psychologist"
    else:
        return "Emergency"


def safety_override(session_id: int, conn,
                    recommendation: str, final_score: float) -> tuple:
    """If any Stage 5 answer was 3 or 4 → force Emergency.

    Returns (recommendation, final_score) — possibly overridden.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM Q_Responses "
            "WHERE session_id = ? AND stage_number = 5 AND cal_score >= 3",
            (session_id,)
        )
        row = cursor.fetchone()
        if row and row.cnt > 0:
            logger.warning("SAFETY OVERRIDE: session %d has Stage 5 answer >= 3.", session_id)
            return "Emergency", 4.0
    except Exception as exc:
        logger.error("Safety override check failed: %s", exc)
    return recommendation, final_score
