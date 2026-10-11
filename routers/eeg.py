"""routers/eeg.py — EEG control endpoints.

Endpoints:
  POST /eeg/connect      - Start EEG stream for a session
  POST /eeg/disconnect   - Stop EEG stream for a session
  GET  /eeg/status/{id}  - Is EEG connected for this session?
  POST /eeg/marker       - Tag current EEG with a question marker
  GET  /eeg/timeline/{session_id} - Get all snapshots for psychologist graph
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_connection
from hardware.eeg_stream import start_eeg_stream, stop_eeg_stream, get_eeg_stream, mark_question
from utils.auth_utils import get_current_user, require_role, check_session_access, require_open_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eeg", tags=["EEG"])


def _check_session_owner(session_id: int, current_user: dict, allow_psychologist: bool = False,
                         must_be_open: bool = False) -> None:
    """Open a short DB connection and make sure this session belongs to the logged-in user."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, session_id, current_user,
                             allow_assigned_psychologist=allow_psychologist)
        if must_be_open:
            require_open_session(cursor, session_id)
    finally:
        conn.close()


class ConnectRequest(BaseModel):
    session_id: int


class MarkerRequest(BaseModel):
    session_id: int
    question_id: int
    question_num: int


@router.post("/connect")
def connect_eeg(req: ConnectRequest, current_user: dict = Depends(require_role("student", "teacher"))):
    """
    Start the EEG stream for a session.
    Call this when the user taps the 'Connect EEG' button in the app.
    BlueMuse must already be running and streaming on this PC.
    """
    _check_session_owner(req.session_id, current_user, must_be_open=True)
    start_eeg_stream(req.session_id)
    # The real state (searching / waiting_signal / connected / no_device) comes from the WebSocket or GET /eeg/status.
    return {"status": "starting", "session_id": req.session_id,
            "message": "Looking for the EEG headset. Make sure BlueMuse is running."}


@router.post("/disconnect")
def disconnect_eeg(req: ConnectRequest, current_user: dict = Depends(require_role("student", "teacher"))):
    """Stop the EEG stream for a session."""
    _check_session_owner(req.session_id, current_user)
    stop_eeg_stream(req.session_id)
    return {"status": "stopped", "session_id": req.session_id}


@router.get("/status/{session_id}")
def eeg_status(session_id: int, current_user: dict = Depends(require_role("student", "teacher"))):
    """Check if EEG stream is active and connected for this session."""
    _check_session_owner(session_id, current_user)
    stream = get_eeg_stream(session_id)
    if not stream:
        return {"session_id": session_id, "running": False, "connected": False, "status": "idle"}
    latest = stream.get_latest()
    return {
        "session_id": session_id,
        "running":    stream.is_alive(),
        "connected":  latest["connected"],
        "status":     latest["status"],
        "latest":     latest,
    }


@router.post("/marker")
def set_question_marker(req: MarkerRequest, current_user: dict = Depends(require_role("student", "teacher"))):
    """
    Tag the EEG stream with the current question being answered.
    Call this every time the user moves to a new question in the questionnaire.
    This allows the psychologist to see EEG values per question later.
    """
    _check_session_owner(req.session_id, current_user)
    mark_question(req.session_id, req.question_id, req.question_num)
    return {"status": "ok", "question_id": req.question_id, "question_num": req.question_num}


@router.get("/timeline/{session_id}")
def eeg_timeline(session_id: int, current_user: dict = Depends(get_current_user)):
    """
    Return all EEG snapshots for a session, used by the psychologist graph.
    Each snapshot has alpha, beta, theta, stress_index, and optionally
    which question was being answered at that moment.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # Session owner, or the psychologist who has an appointment for this session
        check_session_access(cursor, session_id, current_user, allow_assigned_psychologist=True)
        cursor.execute(
            """SELECT snapshot_id, recorded_at, alpha_power, beta_power,
                      theta_power, stress_index, question_id, question_num
               FROM EEG_Snapshots
               WHERE session_id = ?
               ORDER BY recorded_at ASC""",
            (session_id,)
        )
        rows = cursor.fetchall()
        return {
            "session_id": session_id,
            "count": len(rows),
            "snapshots": [
                {
                    "snapshot_id":  r[0],
                    "recorded_at":  r[1].isoformat() if r[1] else None,
                    "alpha":        round(r[2], 4),
                    "beta":         round(r[3], 4),
                    "theta":        round(r[4], 4),
                    "stress_index": round(r[5], 4),
                    "question_id":  r[6],
                    "question_num": r[7],
                }
                for r in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("EEG timeline fetch failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not fetch EEG timeline.")
    finally:
        conn.close()
