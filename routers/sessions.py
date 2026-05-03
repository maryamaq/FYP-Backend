"""routers/sessions.py — Session management endpoints"""

import logging
from fastapi import APIRouter, HTTPException, status

from database import get_connection
from models.session_models import (
    StartSessionRequest,
    StartSessionResponse,
    EndSessionRequest,
    EndSessionResponse,
    SessionDetailResponse,
)
from ml.feature_builder import build_features, get_all_component_scores
from ml.predictor import predict
from utils.time_utils import now_utc
from hardware.bp_reader import find_bp_device, read_bp_once
from signal_processing.lsl_stream import lsl_manager
from signal_processing.window_processor import WindowProcessor
from signal_processing.callbacks import get_closest_emotion, get_questionnaire_score
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["Sessions"])

active_processors = {}

# Maps ML recommendation labels → MH_Results.risk_class CHECK constraint values
RECOMMENDATION_TO_RISK = {
    "Normal":           "Healthy",
    "Calm Down":        "Mild Stress",
    "See Psychologist": "High Risk",
    "Emergency":        "Critical Risk",
}


@router.post("/start", response_model=StartSessionResponse)
def start_session(payload: StartSessionRequest):
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
        session_id: int = cursor.fetchone()[0]
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
def end_session(payload: EndSessionRequest):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Verify session belongs to this user
        cursor.execute(
            "SELECT session_id FROM Sessions WHERE session_id = ? AND user_id = ?",
            (payload.session_id, payload.user_id),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found or does not belong to this user.")

        # Check not already ended
        cursor.execute("SELECT end_time FROM Sessions WHERE session_id = ?", (payload.session_id,))
        row = cursor.fetchone()
        if row and row.end_time is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is already completed.")

        # Mark as ended
        ended_at = now_utc()
        cursor.execute("UPDATE Sessions SET end_time = ? WHERE session_id = ?", (ended_at, payload.session_id))
        conn.commit()

        # Get user role
        cursor.execute("SELECT role FROM Users WHERE user_id = ?", (payload.user_id,))
        user_row = cursor.fetchone()
        role = user_row.role if user_row else "student"

        # Build feature vector & run prediction
        features = build_features(session_id=payload.session_id, user_id=payload.user_id, role=role, conn=conn)
        prediction = predict(features, role)
        recommendation = prediction["recommendation"]
        confidence = prediction["confidence"]

        # Get component scores for saving
        components = get_all_component_scores(session_id=payload.session_id, user_id=payload.user_id, role=role, conn=conn)
        final_score = round(sum(features[0:5]) / 5.0, 4)

        risk_class = RECOMMENDATION_TO_RISK.get(recommendation, "Moderate Risk")
        calculated_at = now_utc()
        cursor.execute(
            """
            INSERT INTO MH_Results (
                session_id, user_id,
                emotional_score, functional_score, context_score,
                isolation_score, critical_score,
                eeg_avg, avg_pulse, avg_bp_systolic,
                dominant_emotion, final_score, risk_class, calculated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.session_id, payload.user_id,
                components["emotional_score"], components["functional_score"],
                components["context_score"], components["isolation_score"],
                components["critical_score"], components["eeg_stress_index"],
                components["pulse_avg"], components["bp_avg_systolic"],
                components["dominant_emotion"], final_score, risk_class, calculated_at,
            ),
        )
        conn.commit()

        logger.info(
            "Session ended: session_id=%d recommendation=%s score=%.2f confidence=%.2f",
            payload.session_id, recommendation, final_score, confidence,
        )
        return EndSessionResponse(
            session_id=payload.session_id,
            recommendation=recommendation,
            final_score=final_score,
            confidence=confidence,
            ended_at=ended_at,
        )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("end_session error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not end session.")
    finally:
        conn.close()


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: int):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id, user_id, start_time, end_time FROM Sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found.")

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM WindowAnalysis WHERE session_id = ?", (session_id,)
        )
        eeg_count = cursor.fetchone().cnt

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM SessionBP WHERE session_id = ?", (session_id,)
        )
        bp_count = cursor.fetchone().cnt

        cursor.execute("SELECT COUNT(*) AS cnt FROM FacialEmotions WHERE session_id = ?", (session_id,))
        emotion_count = cursor.fetchone().cnt

        cursor.execute(
            "SELECT COUNT(DISTINCT stage_number) AS cnt FROM Q_Responses WHERE session_id = ?", (session_id,)
        )
        q_stages = cursor.fetchone().cnt

        return SessionDetailResponse(
            session_id=row.session_id,
            user_id=row.user_id,
            start_time=row.start_time,
            end_time=row.end_time,
            status="completed" if row.end_time else "active",
            eeg_count=eeg_count,
            bp_count=bp_count,
            emotion_count=emotion_count,
            questionnaire_stages=q_stages,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_session error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not retrieve session.")
    finally:
        conn.close()


@router.post("/{session_id}/start_with_muse")
async def start_session_with_muse(session_id: int):
    # 1. Start the LSL Stream
    try:
        lsl_manager.start_stream()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 2. Capture Baseline BP
    baseline_result = {}
    bp_addr = await find_bp_device(scan_timeout=10)
    if bp_addr:
        def on_bp(data): baseline_result.update(data)
        await read_bp_once(bp_addr, on_bp)
    
    baseline_sys = baseline_result.get("systolic") or 120

    # 3. Save Baseline to DB
    conn = get_connection()
    try:
        conn.cursor().execute("""
            INSERT INTO SessionBP (session_id, baseline_sys, baseline_dia, baseline_pulse, baseline_time)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, baseline_result.get("systolic"), baseline_result.get("diastolic"), 
              baseline_result.get("pulse_rate"), datetime.now(timezone.utc)))
        conn.commit()
    finally:
        conn.close()

    # 4. Start 30-Second Window Processor
    callbacks = {"get_emotion": get_closest_emotion, "get_q_score": get_questionnaire_score}
    processor = WindowProcessor(session_id, lsl_manager, baseline_sys, callbacks)
    processor.start()
    
    active_processors[session_id] = processor
    return {"message": "Muse Stream started, Baseline BP captured, Window processing running."}


@router.post("/{session_id}/end_with_muse")
async def end_session_with_muse(session_id: int):
    # 1. Stop Processor
    processor = active_processors.pop(session_id, None)
    if processor:
        processor.stop()

    # 2. Stop LSL Stream
    lsl_manager.stop_stream()

    # 3. Capture After-Session BP
    after_result = {}
    bp_addr = await find_bp_device(scan_timeout=10)
    if bp_addr:
        def on_bp(data): after_result.update(data)
        await read_bp_once(bp_addr, on_bp)

    # 4. Save to DB and calculate Delta
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT baseline_sys, baseline_dia, baseline_pulse FROM SessionBP WHERE session_id = ?", (session_id,))
        row = c.fetchone()
        
        if row and after_result.get("systolic"):
            d_sys = after_result["systolic"] - row[0] if row[0] else None
            d_dia = after_result["diastolic"] - row[1] if row[1] else None
            d_pul = after_result["pulse_rate"] - row[2] if row[2] else None

            c.execute("""
                UPDATE SessionBP SET 
                    after_sys=?, after_dia=?, after_pulse=?, after_time=?,
                    delta_sys=?, delta_dia=?, delta_pulse=?
                WHERE session_id=?
            """, (after_result.get("systolic"), after_result.get("diastolic"), after_result.get("pulse_rate"), 
                  datetime.now(timezone.utc), d_sys, d_dia, d_pul, session_id))
            conn.commit()
    finally:
        conn.close()

    return {"message": "Session ended, BP deltas saved, LSL stopped."}

