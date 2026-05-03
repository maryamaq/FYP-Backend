"""ml/feature_builder.py — Assembles the 16-element feature vector for ML prediction"""

import logging
from typing import List

from preprocessing.emotion_preprocessor import preprocess_emotions
from scoring.questionnaire_scorer import get_stage_scores, score_student, score_teacher

logger = logging.getLogger(__name__)


def _get_student_academic(user_id: int, conn) -> dict:
    defaults = {"cgpa_trend": 0.0, "attendance_drop": 0.0, "failed_courses": 0, "total_courses": 1}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT cgpa_trend, attendance_drop FROM Students WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            defaults["cgpa_trend"] = float(row.cgpa_trend or 0.0)
            defaults["attendance_drop"] = float(row.attendance_drop or 0.0)
    except Exception as exc:
        logger.warning("Could not fetch student academic data for user %d: %s", user_id, exc)
    return defaults


def _get_teacher_workload(user_id: int, conn) -> dict:
    defaults = {"course_load": 0.0, "feedback_trend": 0.0}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT workload_hrs, class_count FROM Teachers WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            defaults["course_load"] = float(row.workload_hrs or 0.0)
            defaults["feedback_trend"] = float(row.class_count or 0.0)
    except Exception as exc:
        logger.warning("Could not fetch teacher data for user %d: %s", user_id, exc)
    return defaults


def _get_window_aggregates(session_id: int, conn) -> dict:
    defaults = {"stress_index": 0.0, "alpha_power": 0.0, "theta_power": 0.0, "hr_mean": 0.0}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT AVG(stress_index), AVG(eeg_alpha), AVG(eeg_theta), AVG(ppg_hr)
            FROM WindowAnalysis WHERE session_id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            defaults["stress_index"] = float(row[0] or 0.0)
            defaults["alpha_power"] = float(row[1] or 0.0)
            defaults["theta_power"] = float(row[2] or 0.0)
            defaults["hr_mean"] = float(row[3] or 0.0)
    except Exception as exc:
        logger.warning("WindowAnalysis query failed for session %d: %s", session_id, exc)
    return defaults

def _get_bp_aggregates(session_id: int, conn) -> dict:
    defaults = {"mean_sys": 0.0, "mean_dia": 0.0, "mean_pulse": 0.0}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT baseline_sys, baseline_dia, baseline_pulse,
                   after_sys, after_dia, after_pulse
            FROM SessionBP WHERE session_id = ?
        """, (session_id,))
        row = cursor.fetchone()
        if row:
            # simple average of baseline and after if available
            sys_vals = [x for x in [row[0], row[3]] if x]
            dia_vals = [x for x in [row[1], row[4]] if x]
            pul_vals = [x for x in [row[2], row[5]] if x]
            
            defaults["mean_sys"] = sum(sys_vals)/len(sys_vals) if sys_vals else 0.0
            defaults["mean_dia"] = sum(dia_vals)/len(dia_vals) if dia_vals else 0.0
            defaults["mean_pulse"] = sum(pul_vals)/len(pul_vals) if pul_vals else 0.0
    except Exception as exc:
        logger.warning("SessionBP query failed for session %d: %s", session_id, exc)
    return defaults


def _get_scores(session_id: int, user_id: int, role: str, conn):
    """Shared helper — returns (q_scores, role_feat_1, role_feat_2, role_feat_3)."""
    stage_scores = get_stage_scores(session_id, conn)
    if role == "student":
        q_data = _get_student_academic(user_id, conn)
        q_scores = score_student(stage_scores, **q_data)
        return q_scores, q_data["cgpa_trend"], q_data["attendance_drop"], q_scores["performance_score"]
    else:
        t_data = _get_teacher_workload(user_id, conn)
        q_scores = score_teacher(stage_scores, course_load=t_data["course_load"], feedback_trend=t_data["feedback_trend"])
        return q_scores, t_data["course_load"], t_data["feedback_trend"], 0.0


def build_features(session_id: int, user_id: int, role: str, conn) -> List[float]:
    """
    Assemble the 16-element feature vector for a session.

    Feature order:
      [0-4]  Questionnaire stage scores (emotional, functional, context, isolation, critical)
      [5-7]  Role-specific features (student: cgpa/attendance/perf | teacher: load/feedback/0)
      [8-10] EEG features (stress_index, alpha_power, theta_power)
      [11]   HR mean
      [12-13] BP (mean_systolic, mean_diastolic)
      [14]   Pulse average
      [15]   Emotion distress score
    """
    logger.info("Building feature vector: session=%d user=%d role=%s", session_id, user_id, role)

    q_scores, rf1, rf2, rf3 = _get_scores(session_id, user_id, role, conn)
    win_agg = _get_window_aggregates(session_id, conn)
    bp_agg = _get_bp_aggregates(session_id, conn)
    emo = preprocess_emotions(session_id, conn)

    features = [
        q_scores["emotional_score"],
        q_scores["functional_score"],
        q_scores["context_score"],
        q_scores["isolation_score"],
        q_scores["critical_score"],
        float(rf1),
        float(rf2),
        float(rf3),
        win_agg["stress_index"],
        win_agg["alpha_power"],
        win_agg["theta_power"],
        win_agg["hr_mean"],
        bp_agg["mean_sys"],
        bp_agg["mean_dia"],
        bp_agg["mean_pulse"],
        float(emo["emotion_distress_score"]),
    ]

    logger.info("Feature vector for session %d: %s", session_id, features)
    return features


def get_all_component_scores(session_id: int, user_id: int, role: str, conn) -> dict:
    """Return all preprocessed component scores as a dict for saving to MH_Results."""
    q_scores, _, _, _ = _get_scores(session_id, user_id, role, conn)
    win_agg = _get_window_aggregates(session_id, conn)
    bp_agg = _get_bp_aggregates(session_id, conn)
    emo = preprocess_emotions(session_id, conn)

    return {
        "emotional_score":       q_scores["emotional_score"],
        "functional_score":      q_scores["functional_score"],
        "context_score":         q_scores["context_score"],
        "isolation_score":       q_scores["isolation_score"],
        "critical_score":        q_scores["critical_score"],
        "performance_score":     q_scores["performance_score"],
        "eeg_stress_index":      win_agg["stress_index"],
        "eeg_alpha_power":       win_agg["alpha_power"],
        "eeg_theta_power":       win_agg["theta_power"],
        "hr_mean":               win_agg["hr_mean"],
        "bp_avg_systolic":       bp_agg["mean_sys"],
        "bp_avg_diastolic":      bp_agg["mean_dia"],
        "pulse_avg":             bp_agg["mean_pulse"],
        "dominant_emotion":      emo["dominant_emotion"],
        "emotion_distress_score": emo["emotion_distress_score"],
    }
