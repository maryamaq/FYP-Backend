"""routers/results.py — Mental health result endpoints."""

import logging
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from database import get_connection
from models.result_models import (
    SessionResult, ScoreBreakdown, UserHistory, UserHistoryItem,
    UnreliableModality, AppointmentInfo,
)
from utils.auth_utils import get_current_user, require_same_user, check_session_access

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/results", tags=["Results"])

# A user should take an assessment every 14 days: next due = last completed session end_time + 14 days.
ASSESSMENT_INTERVAL_DAYS = 14

# Display tier for the app (nothing is stored): stored risk label -> Low / Medium / High
_TIER = {
    "Healthy": "Low",
    "Mild Stress": "Medium", "Moderate Risk": "Medium",
    "High Risk": "High", "Critical Risk": "High",
}


def _next_assessment_due(items: List[UserHistoryItem]):
    """Return (next_due_date, due_status) from the real rows, or (None, None) if nothing completed yet."""
    finished = [i.end_time for i in items if i.end_time and i.recommendation]
    if not finished:
        return None, None

    next_due = max(finished) + timedelta(days=ASSESSMENT_INTERVAL_DAYS)
    days_left = (next_due.date() - datetime.now().date()).days
    if days_left <= 0:
        status_text = "due now"
    elif days_left == 1:
        status_text = "due in 1 day"
    else:
        status_text = f"due in {days_left} days"
    return next_due, status_text


@router.get("/user/{user_id}", response_model=UserHistory)
def get_user_history(user_id: int, current_user: dict = Depends(get_current_user)):
    """Return all completed session results for a user (only your own history)."""
    require_same_user(current_user, user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM Users WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found.")

        cursor.execute("""
            SELECT s.session_id, s.start_time, s.end_time,
                   r.risk_class AS recommendation, r.final_score, r.calculated_at
            FROM Sessions s LEFT JOIN MH_Results r ON s.session_id = r.session_id
            WHERE s.user_id = ? ORDER BY s.start_time DESC""", (user_id,))

        items = [
            UserHistoryItem(session_id=row.session_id, start_time=row.start_time, end_time=row.end_time,
                            recommendation=row.recommendation, final_score=row.final_score,
                            calculated_at=row.calculated_at)
            for row in cursor.fetchall()
        ]
        next_due, due_status = _next_assessment_due(items)
        return UserHistory(user_id=user_id, sessions=items,
                           next_due_date=next_due, due_status=due_status)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_user_history error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve history.")
    finally:
        conn.close()


@router.get("/{session_id}", response_model=SessionResult)
def get_session_result(session_id: int, current_user: dict = Depends(get_current_user)):
    """Return the full result with score breakdown (session owner, assigned psychologist, or notified advisor)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, session_id, current_user,
                             allow_assigned_psychologist=True, allow_notified_advisor=True)
        cursor.execute("""
            SELECT r.session_id, s.user_id, u.role AS user_role,
                   r.emotional_score, r.functional_score, r.context_score,
                   r.isolation_score, r.critical_score,
                   r.eeg_avg, r.avg_pulse, r.avg_bp_systolic,
                   r.dominant_emotion, r.final_score, r.risk_class,
                   r.calculated_at, s.start_time, s.end_time,
                   r.questionnaire_score, r.physio_score, r.missing_modalities
            FROM MH_Results r
            INNER JOIN Sessions s ON r.session_id = s.session_id
            INNER JOIN Users u ON s.user_id = u.user_id
            WHERE r.session_id = ?""", (session_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"No result for session {session_id}.")

        duration = None
        if row.start_time and row.end_time:
            duration = round((row.end_time - row.start_time).total_seconds() / 60.0, 2)

        # missing_modalities IS NULL = saved before the data checks existed ("legacy").
        # Its eeg/pulse/bp/face values may be placeholders (0, 72.0, 'neutral'), so they are
        # returned as None and never recomputed. New rows return exactly what was stored.
        legacy = row.missing_modalities is None
        if legacy:
            missing = []
            unreliable = [UnreliableModality(name=n, reason="recorded before data checks")
                          for n in ("eeg", "hr", "bp")]
            eeg_avg = avg_pulse = avg_bp = dominant_emotion = None
        else:
            missing = [m for m in row.missing_modalities.split(",") if m]
            unreliable = []
            eeg_avg, avg_pulse, avg_bp = row.eeg_avg, row.avg_pulse, row.avg_bp_systolic
            dominant_emotion = row.dominant_emotion

        breakdown = ScoreBreakdown(
            emotional=row.emotional_score or 0.0,
            functional=row.functional_score or 0.0,
            context=row.context_score or 0.0,
            isolation=row.isolation_score or 0.0,
            critical=row.critical_score,
            questionnaire_score=row.questionnaire_score,
            physio_score=row.physio_score,
            eeg_stress_index=eeg_avg,
            hr_mean=avg_pulse,
            bp_avg_systolic=avg_bp,
            dominant_emotion=dominant_emotion,
        )

        referral_note = None
        risk_class = row.risk_class or "Healthy"
        if risk_class in ["Mild Stress", "Moderate Risk"]:
            cursor.execute("""
                SELECT u.name FROM Users u 
                JOIN Sections s ON u.user_id = s.advisor_id 
                JOIN Students st ON s.section_id = st.section_id 
                WHERE st.user_id = ?
            """, (row.user_id,))
            adv = cursor.fetchone()
            if adv:
                referral_note = f"Please schedule a meeting with your advisor: {adv[0]}."
        elif risk_class in ["High Risk", "Critical Risk"]:
            cursor.execute("""
                SELECT u.name FROM Users u
                JOIN Appointments a ON u.user_id = a.psychologist_id
                WHERE a.session_id = ?
            """, (session_id,))
            psych = cursor.fetchone()
            if psych:
                referral_note = f"An appointment has been automatically scheduled with Dr. {psych[0]}."

        cursor.execute("SELECT COUNT(*) FROM AdvisorNotifications WHERE session_id = ?", (session_id,))
        advisor_notified = cursor.fetchone()[0] > 0

        appointment = None
        cursor.execute("""
            SELECT TOP 1 a.appointment_id, u.name, a.status
            FROM Appointments a JOIN Users u ON u.user_id = a.psychologist_id
            WHERE a.session_id = ? ORDER BY a.appointment_id DESC""", (session_id,))
        appt = cursor.fetchone()
        if appt:
            appointment = AppointmentInfo(appointment_id=appt[0], psychologist_name=appt[1], status=appt[2])

        return SessionResult(
            session_id=row.session_id, user_id=row.user_id, user_role=row.user_role,
            recommendation=risk_class, referral_note=referral_note, final_score=row.final_score or 0.0,
            score_breakdown=breakdown, session_duration_minutes=duration,
            calculated_at=row.calculated_at,
            tier=_TIER.get(risk_class, "Low"), missing_modalities=missing,
            unreliable_modalities=unreliable, advisor_notified=advisor_notified,
            appointment=appointment, legacy=legacy)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_session_result error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve result.")
    finally:
        conn.close()
