"""routers/questionnaire.py — Questionnaire endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from database import get_connection
from models.questionnaire_models import (
    SubmitStageRequest, SubmitStageResponse, StageInfo, QuestionInfo,
)
from utils.auth_utils import get_current_user, require_role
from utils.time_utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/questionnaire", tags=["Questionnaire"])

MAX_STAGES = 5


@router.post("/submit", response_model=SubmitStageResponse)
def submit_stage(payload: SubmitStageRequest,
                 current_user: dict = Depends(require_role("student", "teacher"))):
    """Submit answers for one questionnaire stage (only into your own session)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Lock the session row first: checks the owner and makes two quick taps on
        #    "Submit" run one after the other (the second one then sees the stored rows).
        cursor.execute("SELECT user_id, end_time FROM Sessions WITH (UPDLOCK, HOLDLOCK) WHERE session_id = ?",
                       (payload.session_id,))
        session_row = cursor.fetchone()
        if not session_row or session_row.user_id != current_user["user_id"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
        if session_row.end_time is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended.")

        cursor.execute("SELECT threshold FROM Q_Stages WHERE stage_number = ?", (payload.stage_number,))
        stage_row = cursor.fetchone()
        if not stage_row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Stage {payload.stage_number} not found.")

        # 2. Stage already submitted for this session: do not insert again, answer from the stored rows.
        cursor.execute("SELECT cal_score FROM Q_Responses WHERE session_id = ? AND stage_number = ?",
                       (payload.session_id, payload.stage_number))
        stored_rows = cursor.fetchall()
        if stored_rows:
            total_score = sum(r.cal_score for r in stored_rows)
            conn.rollback()   # nothing to save; releases the session lock
        else:
            # 3. The answers must be exactly the questions of this stage for this role (no repeats, none missing).
            cursor.execute("""
                SELECT q.question_id, q.weight
                FROM Q_Questions q INNER JOIN Q_Stages s ON q.stage_id = s.stage_id
                WHERE s.stage_number = ? AND (s.target_role = ? OR s.target_role = 'both')""",
                (payload.stage_number, current_user["role"]))
            weights = {r.question_id: r.weight for r in cursor.fetchall()}
            sent_ids = [a.question_id for a in payload.answers]
            if len(sent_ids) != len(set(sent_ids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail="Each question must be answered only once.")
            if set(sent_ids) != set(weights):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail="Answers must be exactly the questions of this stage.")

            # 4. The server calculates the score (the client cal_score is ignored).
            now = now_utc()
            rows = [(payload.session_id, a.question_id, payload.stage_number, str(a.response_choice),
                     a.response_choice * weights[a.question_id], now) for a in payload.answers]
            cursor.executemany("""
                INSERT INTO Q_Responses (session_id, question_id, stage_number, response_choice, cal_score, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)""", rows)
            total_score = sum(row[4] for row in rows)
            conn.commit()
        passed = total_score >= stage_row.threshold

        if passed and payload.stage_number < MAX_STAGES:
            next_stage = payload.stage_number + 1
            message = f"Stage {payload.stage_number} passed. Proceed to stage {next_stage}."
        elif passed:
            next_stage = None
            message = "All stages completed. Session can now be ended."
        else:
            next_stage = None
            message = f"Stage {payload.stage_number} did not meet threshold."

        logger.info("Stage %d submitted: session=%d score=%.2f passed=%s",
                     payload.stage_number, payload.session_id, total_score, passed)
        return SubmitStageResponse(stage_number=payload.stage_number, total_score=round(total_score, 4),
                                    passed=passed, next_stage=next_stage, message=message)
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("submit_stage error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not submit stage.")
    finally:
        conn.close()


@router.get("/stages", response_model=List[StageInfo])
def get_stages(current_user: dict = Depends(get_current_user)):
    """Return all questionnaire stages."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT stage_id, stage_number, stage_name, target_role, threshold FROM Q_Stages ORDER BY stage_number")
        return [StageInfo(stage_id=r.stage_id, stage_number=r.stage_number, stage_name=r.stage_name,
                          target_role=r.target_role, threshold=r.threshold) for r in cursor.fetchall()]
    except Exception as exc:
        logger.exception("get_stages error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve stages.")
    finally:
        conn.close()


@router.get("/questions/{stage_number}", response_model=List[QuestionInfo])
def get_questions(stage_number: int, role: Optional[str] = Query(None, description="Filter: student or teacher"),
                  current_user: dict = Depends(get_current_user)):
    """Return questions for a stage, optionally filtered by role."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if role:
            cursor.execute("""
                SELECT q.question_id, q.stage_id, q.question_text, q.weight
                FROM Q_Questions q INNER JOIN Q_Stages s ON q.stage_id = s.stage_id
                WHERE s.stage_number = ? AND (s.target_role = ? OR s.target_role = 'both')
                ORDER BY q.question_id""", (stage_number, role))
        else:
            cursor.execute("""
                SELECT q.question_id, q.stage_id, q.question_text, q.weight
                FROM Q_Questions q INNER JOIN Q_Stages s ON q.stage_id = s.stage_id
                WHERE s.stage_number = ? ORDER BY q.question_id""", (stage_number,))

        return [QuestionInfo(question_id=r.question_id, stage_id=r.stage_id,
                             question_text=r.question_text, weight=r.weight) for r in cursor.fetchall()]
    except Exception as exc:
        logger.exception("get_questions error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve questions.")
    finally:
        conn.close()
