"""routers/sessions.py — Session lifecycle: start, end (with scoring), and detail."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from database import get_connection
from models.session_models import (
    StartSessionRequest, StartSessionResponse,
    EndSessionRequest, EndSessionResponse, SessionDetailResponse,
)
from processing.scorer import (
    get_stage_scores, calc_student_score, calc_teacher_score,
    classify, safety_override, fuse_with_missing,
    get_heart_rate, get_bp_change, hr_score, bp_score,
)
from processing.appointments import assign_psychologist, notify_advisor
from processing.eeg import preprocess_eeg
from processing.emotions import preprocess_emotions
from utils.auth_utils import get_current_user, require_role, require_same_user, check_session_access
from utils.time_utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["Sessions"])

# Maps recommendation labels to MH_Results.risk_class CHECK constraint values
_RISK_MAP = {
    "Normal": "Healthy",
    "Calm Down": "Mild Stress",
    "See Psychologist": "High Risk",
    "Emergency": "Critical Risk",
}


@router.post("/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest,
                  current_user: dict = Depends(require_role("student", "teacher"))):
    """Create a new assessment session (only for the logged-in student/teacher)."""
    require_same_user(current_user, payload.user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM Users WHERE user_id = ?", (payload.user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {payload.user_id} not found.")

        started_at = now_utc()
        cursor.execute(
            "INSERT INTO Sessions (user_id, start_time) OUTPUT INSERTED.session_id VALUES (?, ?)",
            (payload.user_id, started_at),
        )
        session_id = cursor.fetchone()[0]
        conn.commit()
        logger.info("Session started: session_id=%d user_id=%d", session_id, payload.user_id)
        return StartSessionResponse(session_id=session_id, started_at=started_at)
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("start_session error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start session.")
    finally:
        conn.close()


@router.post("/end", response_model=EndSessionResponse)
def end_session(payload: EndSessionRequest,
                current_user: dict = Depends(require_role("student", "teacher"))):
    """End a session, score it and save the result. All DB writes happen in ONE transaction:
    if anything fails the session stays open and the user can try again."""
    require_same_user(current_user, payload.user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Verify session (must belong to the logged-in user and still be open)
        cursor.execute("SELECT session_id, end_time FROM Sessions WHERE session_id = ? AND user_id = ?",
                        (payload.session_id, payload.user_id))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
        if row.end_time is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended.")

        # 2. Stop the EEG stream FIRST so its last snapshots are saved before we read them.
        #    (If scoring fails later the stream is not restarted; a retry uses the saved snapshots.)
        try:
            from hardware.eeg_stream import stop_eeg_stream
            stop_eeg_stream(payload.session_id)
        except Exception:
            logger.warning("Could not stop EEG stream for session %d.", payload.session_id)

        # 3. Questionnaire score (formulas unchanged)
        role = current_user["role"]
        stages = get_stage_scores(payload.session_id, conn)
        if role == "student":
            cursor.execute("SELECT cgpa_trend, attendance_drop FROM Students WHERE user_id = ?", (payload.user_id,))
            s = cursor.fetchone()
            q_score = calc_student_score(stages,
                                         cgpa_trend=float(s.cgpa_trend or 0) if s else 0.0,
                                         attendance_drop=float(s.attendance_drop or 0) if s else 0.0)
        else:
            cursor.execute("SELECT workload_hrs FROM Teachers WHERE user_id = ?", (payload.user_id,))
            t = cursor.fetchone()
            q_score = calc_teacher_score(stages, course_load=float(t.workload_hrs or 0) if t else 0.0)

        # 4. Each physiological signal is a value, or None when it was not really measured
        eeg = preprocess_eeg(payload.session_id, conn)
        emo = preprocess_emotions(payload.session_id, conn)
        avg_hr = get_heart_rate(payload.session_id, conn)
        bp = get_bp_change(payload.session_id, conn)
        signals = {
            "eeg": eeg["eeg_score"] if eeg else None,
            "face": emo["face_score"] if emo else None,
            "hr": hr_score(avg_hr) if avg_hr is not None else None,
            "bp": bp_score(bp["delta"]) if bp else None,
        }

        # 5. Final score: 0.70 * questionnaire + 0.30 * physiological (missing signals left out)
        fused = fuse_with_missing(q_score, signals)
        final = fused["final"]
        recommendation = classify(final)
        recommendation, final = safety_override(payload.session_id, conn, recommendation, final)
        risk_class = _RISK_MAP.get(recommendation, "Moderate Risk")
        missing_modalities = ",".join(fused["missing_modalities"])

        # 6. Close the session. The AND end_time IS NULL makes a double tap harmless:
        #    the second request updates 0 rows and gets 409.
        ended_at = now_utc()
        cursor.execute("UPDATE Sessions SET end_time = ?, status = 'completed' "
                       "WHERE session_id = ? AND end_time IS NULL", (ended_at, payload.session_id))
        if cursor.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended.")

        # 7. Save the result. NULL means "not measured" (never 0 or a default value).
        cursor.execute("""
            INSERT INTO MH_Results (
                session_id, user_id, emotional_score, functional_score,
                context_score, isolation_score, critical_score,
                eeg_avg, avg_pulse, avg_bp_systolic,
                dominant_emotion, final_score, risk_class, calculated_at,
                questionnaire_score, physio_score, missing_modalities
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.session_id, payload.user_id,
             stages.get(1, 0.0), stages.get(2, 0.0), stages.get(3, 0.0),
             stages.get(4, 0.0), stages.get(5, 0.0),
             eeg["stress_index"] if eeg else None,
             avg_hr,
             bp["first_systolic"] if bp else None,
             emo["dominant_emotion"] if emo else None,
             final, risk_class, now_utc(),
             q_score, fused["physio"], missing_modalities))

        # 8. Risk actions (same transaction): Medium -> tell the advisor, High/Critical -> book a psychologist
        referral_note = None
        if risk_class in ["Mild Stress", "Moderate Risk"]:
            advisor_name = notify_advisor(cursor, payload.user_id, payload.session_id, risk_class)
            if advisor_name:
                referral_note = f"Please schedule a meeting with your advisor: {advisor_name}."
        elif risk_class in ["High Risk", "Critical Risk"]:
            booking = assign_psychologist(cursor, payload.user_id, payload.session_id)
            if booking:
                referral_note = f"An appointment has been automatically scheduled with Dr. {booking['psychologist_name']}."
        conn.commit()

        logger.info("Session %d ended: recommendation=%s missing=%s", payload.session_id,
                    recommendation, missing_modalities or "none")
        return EndSessionResponse(
            session_id=payload.session_id, recommendation=recommendation,
            referral_note=referral_note, final_score=final,
            confidence=0.0, ended_at=ended_at,
            risk_class=risk_class, missing_modalities=fused["missing_modalities"]
        )
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("end_session error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Could not end session, please try again.")
    finally:
        conn.close()


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: int, current_user: dict = Depends(get_current_user)):
    """Return session details with data counts (only the session owner)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, session_id, current_user)
        cursor.execute("SELECT session_id, user_id, start_time, end_time FROM Sessions WHERE session_id = ?",
                        (session_id,))
        row = cursor.fetchone()

        cursor.execute("SELECT COUNT(*) AS cnt FROM SensorData WHERE session_id = ? AND data_type = 'eeg'", (session_id,))
        eeg_count = cursor.fetchone().cnt
        cursor.execute("SELECT COUNT(*) AS cnt FROM SensorData WHERE session_id = ? AND data_type = 'bp'", (session_id,))
        bp_count = cursor.fetchone().cnt
        cursor.execute("SELECT COUNT(*) AS cnt FROM FacialEmotions WHERE session_id = ?", (session_id,))
        emotion_count = cursor.fetchone().cnt
        cursor.execute("SELECT COUNT(DISTINCT stage_number) AS cnt FROM Q_Responses WHERE session_id = ?", (session_id,))
        q_stages = cursor.fetchone().cnt

        return SessionDetailResponse(
            session_id=row.session_id, user_id=row.user_id,
            start_time=row.start_time, end_time=row.end_time,
            status="completed" if row.end_time else "active",
            eeg_count=eeg_count, bp_count=bp_count,
            emotion_count=emotion_count, questionnaire_stages=q_stages)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_session error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve session.")
    finally:
        conn.close()
