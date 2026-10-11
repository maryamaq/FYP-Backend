"""routers/psychologist.py — Psychologist endpoints for appointments and adaptive feedback."""

import logging
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from database import get_connection
from utils.auth_utils import require_role, require_same_user, check_session_access
from utils.time_utils import format_dt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/psychologist", tags=["Psychologist"])

# Feedback labels and the score saved with each one. Feedback never changes a question weight.
LABEL_SCORES = {"useful": 5, "less_useful": 3, "irrelevant": 1}

class FeedbackRequest(BaseModel):
    psychologist_id: int
    question_id: int
    usefulness_label: Optional[str] = None    # 'useful' | 'less_useful' | 'irrelevant'
    usefulness_score: Optional[int] = None    # 1 to 5 (older clients send only this)
    comments: Optional[str] = None            # max 500 characters
    session_id: Optional[int] = None          # session the psychologist was reviewing


def label_to_score(label: str) -> int:
    """useful = 5, less_useful = 3, irrelevant = 1."""
    return LABEL_SCORES[label]


def score_to_label(score: int) -> str:
    """Used only when an older client sends a score without a label."""
    if score >= 4:
        return "useful"
    if score >= 2:
        return "less_useful"
    return "irrelevant"


def resolve_feedback(label: Optional[str], score: Optional[int]):
    """Return (label, score) to store, or raise ValueError with a message for a 422."""
    if label is None and score is None:
        raise ValueError("Send a usefulness label or a score.")
    if label is not None and label not in LABEL_SCORES:
        raise ValueError("Label must be useful, less_useful or irrelevant.")
    if score is not None and not 1 <= score <= 5:
        raise ValueError("Score must be between 1 and 5.")
    if label is None:
        return score_to_label(score), score
    if score is not None and score != label_to_score(label):
        raise ValueError("Score does not match the label.")
    return label, label_to_score(label)


def stage_at(offset_sec: float, boundaries: list):
    """
    Which questionnaire stage was running at this moment?
    boundaries = [(stage_number, submit_offset_sec), ...] sorted by time. Answers are saved when a
    stage is submitted, so a stage runs from the previous submit (or the session start) to its own submit.
    Before the first submit -> stage 1's window. After the last submit -> None.
    """
    for stage_number, end_sec in boundaries:
        if offset_sec <= end_sec:
            return stage_number
    return None

@router.get("/{psychologist_id}/appointments")
def get_appointments(psychologist_id: int,
                     current_user: dict = Depends(require_role("psychologist"))):
    """Get all students assigned to this psychologist (only your own list)."""
    require_same_user(current_user, psychologist_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.appointment_id, a.student_id, u.name as student_name, 
                   a.session_id, a.status, a.created_at, m.risk_class as recommendation
            FROM Appointments a
            JOIN Users u ON a.student_id = u.user_id
            LEFT JOIN MH_Results m ON a.session_id = m.session_id
            WHERE a.psychologist_id = ?
            ORDER BY a.created_at DESC
            """, (psychologist_id,)
        )
        rows = cursor.fetchall()
        appointments = []
        for r in rows:
            appointments.append({
                "appointment_id": r[0],
                "student_id": r[1],
                "student_name": r[2],
                "session_id": r[3],
                "status": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "recommendation": r[6] or "Pending"
            })
        return {"appointments": appointments}
    except Exception as exc:
        logger.exception("Error getting appointments: %s", exc)
        raise HTTPException(status_code=500, detail="Could not fetch appointments.")
    finally:
        conn.close()

class AppointmentStatusRequest(BaseModel):
    status: str  # 'Completed' or 'Cancelled'

@router.post("/appointments/{appointment_id}/status")
def update_appointment_status(appointment_id: int, payload: AppointmentStatusRequest,
                              current_user: dict = Depends(require_role("psychologist"))):
    """Psychologist closes one of their own appointments: Scheduled -> Completed or Cancelled."""
    if payload.status not in ("Completed", "Cancelled"):
        raise HTTPException(status_code=422, detail="Status must be Completed or Cancelled.")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM Appointments WHERE appointment_id = ? AND psychologist_id = ?",
                       (appointment_id, current_user["user_id"]))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Appointment not found.")
        if row[0] == payload.status:
            return {"appointment_id": appointment_id, "status": row[0]}   # same status again: no change
        if row[0] != "Scheduled":
            raise HTTPException(status_code=409, detail="Only a Scheduled appointment can be changed.")
        cursor.execute("UPDATE Appointments SET status = ? WHERE appointment_id = ? AND status = 'Scheduled'",
                       (payload.status, appointment_id))
        conn.commit()
        return {"appointment_id": appointment_id, "status": payload.status}
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("Error updating appointment: %s", exc)
        raise HTTPException(status_code=500, detail="Could not update the appointment.")
    finally:
        conn.close()

@router.post("/feedback")
def submit_question_feedback(payload: FeedbackRequest,
                             current_user: dict = Depends(require_role("psychologist"))):
    """
    Psychologist says how useful a question was. One row per (psychologist, question):
    a second feedback for the same question updates the first. It never changes a question weight.
    """
    require_same_user(current_user, payload.psychologist_id)
    try:
        label, score = resolve_feedback(payload.usefulness_label, payload.usefulness_score)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    comments = (payload.comments or "").strip()
    if len(comments) > 500:
        raise HTTPException(status_code=422, detail="Comment must be 500 characters or less.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM Q_Questions WHERE question_id = ?", (payload.question_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Question not found.")
        if payload.session_id is not None:
            check_session_access(cursor, payload.session_id, current_user, allow_assigned_psychologist=True)

        # Upsert: try UPDATE first, INSERT when there was nothing to update
        cursor.execute(
            """UPDATE QuestionFeedback
               SET usefulness_label = ?, usefulness_score = ?, comments = ?, session_id = ?, updated_at = GETDATE()
               WHERE psychologist_id = ? AND question_id = ?""",
            (label, score, comments or None, payload.session_id, payload.psychologist_id, payload.question_id)
        )
        if cursor.rowcount == 0:
            cursor.execute(
                """INSERT INTO QuestionFeedback
                   (psychologist_id, question_id, usefulness_score, usefulness_label, comments, session_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, GETDATE())""",
                (payload.psychologist_id, payload.question_id, score, label, comments or None, payload.session_id)
            )
        conn.commit()
        return {"message": "Feedback submitted successfully.", "usefulness_label": label, "usefulness_score": score}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("Error saving feedback: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save feedback.")
    finally:
        conn.close()

@router.get("/feedback/summary")
def feedback_summary(current_user: dict = Depends(require_role("psychologist"))):
    """How psychologists rated each question (counts per label). Read-only, from the database view."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT question_id, stage_id, question_text, feedback_count, avg_score,
                      useful_count, less_useful_count, irrelevant_count
               FROM vw_QuestionFeedbackSummary
               WHERE feedback_count > 0
               ORDER BY stage_id, question_id"""
        )
        return {"questions": [
            {
                "question_id": r[0], "stage_id": r[1], "question_text": r[2],
                "feedback_count": r[3], "avg_score": r[4],
                "useful": r[5], "less_useful": r[6], "irrelevant": r[7],
            } for r in cursor.fetchall()
        ]}
    except Exception as exc:
        logger.exception("Error getting feedback summary: %s", exc)
        raise HTTPException(status_code=500, detail="Could not fetch the feedback summary.")
    finally:
        conn.close()

@router.get("/session/{session_id}/review")
def get_session_review(session_id: int,
                       current_user: dict = Depends(require_role("psychologist"))):
    """
    Everything the review screen needs for one session (only if it is assigned to this psychologist):
    result, questionnaire stages with answers, EEG points and face images.
    Every point has offset_sec = seconds since Sessions.start_time.
    Empty lists are normal (no EEG headset, camera off).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, session_id, current_user, allow_assigned_psychologist=True)

        cursor.execute(
            """SELECT s.start_time, s.end_time, u.name, u.role
               FROM Sessions s JOIN Users u ON u.user_id = s.user_id
               WHERE s.session_id = ?""", (session_id,))
        s = cursor.fetchone()
        start_time = s.start_time

        def offset(moment):
            return round((moment - start_time).total_seconds(), 1)

        session = {"session_id": session_id, "student_name": s.name, "role": s.role,
                   "start_time": format_dt(s.start_time), "end_time": format_dt(s.end_time)}

        result = None
        cursor.execute(
            """SELECT final_score, risk_class, questionnaire_score, physio_score, missing_modalities, calculated_at
               FROM MH_Results WHERE session_id = ?""", (session_id,))
        r = cursor.fetchone()
        if r:
            missing = None      # NULL = result saved before missing-data tracking existed
            if r.missing_modalities is not None:
                missing = [m for m in r.missing_modalities.split(",") if m]
            result = {"final_score": r.final_score, "risk_class": r.risk_class,
                      "questionnaire_score": r.questionnaire_score, "physio_score": r.physio_score,
                      "missing_modalities": missing, "calculated_at": format_dt(r.calculated_at)}

        # Answers, grouped by stage. A stage's time window ends when it was submitted.
        cursor.execute(
            """SELECT r.stage_number, st.stage_name, q.question_id, q.question_text,
                      CASE r.response_choice
                           WHEN '0' THEN 'Never' WHEN '1' THEN 'Rarely' WHEN '2' THEN 'Sometimes'
                           WHEN '3' THEN 'Often' WHEN '4' THEN 'Always' ELSE r.response_choice
                      END AS answer_text,
                      r.cal_score, r.timestamp
               FROM Q_Responses r
               JOIN Q_Questions q ON q.question_id = r.question_id
               LEFT JOIN Q_Stages st ON st.stage_number = r.stage_number
               WHERE r.session_id = ?
               ORDER BY r.stage_number, q.question_id""", (session_id,))
        stages = []
        for a in cursor.fetchall():
            if not stages or stages[-1]["stage_number"] != a.stage_number:
                stages.append({"stage_number": a.stage_number, "stage_name": a.stage_name,
                               "start_sec": 0, "end_sec": offset(a.timestamp), "answers": []})
            stages[-1]["answers"].append({"question_id": a.question_id, "question_text": a.question_text,
                                          "answer_text": a.answer_text, "cal_score": a.cal_score})
        stages.sort(key=lambda st: st["end_sec"])
        previous_end = 0
        for st in stages:
            st["start_sec"] = previous_end
            previous_end = st["end_sec"]
        boundaries = [(st["stage_number"], st["end_sec"]) for st in stages]

        cursor.execute(
            """SELECT recorded_at, alpha_power, beta_power, theta_power, stress_index, question_id, question_num
               FROM EEG_Snapshots WHERE session_id = ? ORDER BY recorded_at""", (session_id,))
        eeg = []
        for e in cursor.fetchall():
            sec = offset(e.recorded_at)
            eeg.append({"offset_sec": sec, "recorded_at": format_dt(e.recorded_at),
                        "alpha": e.alpha_power, "beta": e.beta_power, "theta": e.theta_power,
                        "stress_index": e.stress_index, "stage_number": stage_at(sec, boundaries),
                        "question_id": e.question_id, "question_num": e.question_num})

        cursor.execute(
            """SELECT emotion_id, captured_at, dominant_emotion, image_path
               FROM FacialEmotions WHERE session_id = ? ORDER BY captured_at""", (session_id,))
        faces = []
        for f in cursor.fetchall():
            sec = offset(f.captured_at)
            faces.append({"emotion_id": f.emotion_id, "offset_sec": sec,
                          "captured_at": format_dt(f.captured_at), "dominant_emotion": f.dominant_emotion,
                          "stage_number": stage_at(sec, boundaries), "has_image": bool(f.image_path)})

        return {"session": session, "result": result, "stages": stages, "eeg": eeg, "faces": faces}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error building session review: %s", exc)
        raise HTTPException(status_code=500, detail="Could not build the session review.")
    finally:
        conn.close()

@router.get("/questions/all")
def get_all_questions_for_feedback(current_user: dict = Depends(require_role("psychologist"))):
    """Fetch all questions for the psychologist to provide feedback on."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT question_id, stage_id, question_text FROM Q_Questions ORDER BY stage_id, question_id")
        rows = cursor.fetchall()
        return {"questions": [{"question_id": r[0], "stage_id": r[1], "question_text": r[2]} for r in rows]}
    finally:
        conn.close()

@router.get("/session/{session_id}/answers")
def get_session_answers(session_id: int,
                        current_user: dict = Depends(require_role("psychologist"))):
    """Fetch the questionnaire answers for a session (only if it is assigned to this psychologist)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, session_id, current_user, allow_assigned_psychologist=True)
        # Answer text is the 0-4 scale label shown in the app; weight is the saved cal_score.
        cursor.execute("""
            SELECT q.question_id, q.question_text,
                   CASE r.response_choice
                        WHEN '0' THEN 'Never' WHEN '1' THEN 'Rarely' WHEN '2' THEN 'Sometimes'
                        WHEN '3' THEN 'Often' WHEN '4' THEN 'Always' ELSE r.response_choice
                   END AS answer_text,
                   r.cal_score
            FROM Q_Responses r
            JOIN Q_Questions q ON r.question_id = q.question_id
            WHERE r.session_id = ?
            ORDER BY q.stage_id, q.question_id
        """, (session_id,))
        rows = cursor.fetchall()
        return {"answers": [
            {
                "question_id": r[0],
                "question_text": r[1],
                "answer_text": r[2],
                "weight": r[3]
            } for r in rows
        ]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting answers: %s", exc)
        raise HTTPException(status_code=500, detail="Could not fetch answers.")
    finally:
        conn.close()
