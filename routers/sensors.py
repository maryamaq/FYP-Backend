"""routers/sensors.py — Biometric sensor data endpoints (pulse, BP, emotion)."""

import base64
import logging
import os

import cv2
import numpy as np
from deepface import DeepFace
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from config import settings
from database import get_connection
from models.sensor_models import (
    BPRequest, BPResponse, EmotionRequest, EmotionResponse,
    PulseRequest, PulseResponse,
)
from utils.auth_utils import (
    get_current_user, require_role, require_same_user, check_session_access, require_open_session,
)
from utils.time_utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sensors", tags=["Sensors"])

MAX_IMAGE_BYTES = int(2.5 * 1024 * 1024)   # largest camera frame we accept
MAX_STAGE = 5


@router.post("/pulse", response_model=PulseResponse)
def record_pulse(payload: PulseRequest,
                 current_user: dict = Depends(require_role("student", "teacher"))):
    """Save a pulse/heart-rate reading to SensorData (only into your own session)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, payload.session_id, current_user)
        recorded_at = now_utc()
        cursor.execute(
            "INSERT INTO SensorData (session_id, pulse_rate, data_type, recorded_at) VALUES (?, ?, 'ppg', ?)",
            (payload.session_id, int(payload.pulse_rate), recorded_at),
        )
        conn.commit()
        logger.info("Pulse recorded: session=%d rate=%.1f", payload.session_id, payload.pulse_rate)
        return PulseResponse(session_id=payload.session_id, pulse_rate=payload.pulse_rate,
                             source=payload.source, recorded_at=recorded_at)
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("record_pulse error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store pulse.")
    finally:
        conn.close()


@router.post("/bp", response_model=BPResponse)
def record_bp(payload: BPRequest,
              current_user: dict = Depends(require_role("student", "teacher"))):
    """Save a blood pressure reading to SensorData (only into your own session)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        check_session_access(cursor, payload.session_id, current_user)
        recorded_at = now_utc()
        cursor.execute(
            "INSERT INTO SensorData (session_id, bp_systolic, bp_diastolic, pulse_rate, data_type, recorded_at) "
            "VALUES (?, ?, ?, ?, 'bp', ?)",
            (payload.session_id, payload.systolic, payload.diastolic, payload.pulse_rate, recorded_at),
        )
        conn.commit()
        logger.info("BP recorded: session=%d sys=%d dia=%d", payload.session_id, payload.systolic, payload.diastolic)
        return BPResponse(session_id=payload.session_id, systolic=payload.systolic,
                          diastolic=payload.diastolic, pulse_rate=payload.pulse_rate, recorded_at=recorded_at)
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.exception("record_bp error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store BP.")
    finally:
        conn.close()


def decode_camera_frame(image_base64: str):
    """Base64 text -> OpenCV image. Raises HTTP 422 if it is not a valid picture or is too big."""
    if len(image_base64) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Image is too large.")
    try:
        img_bytes = base64.b64decode(image_base64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Image is not valid base64.")
    if len(img_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Image is too large.")
    try:
        frame = cv2.imdecode(np.frombuffer(img_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:       # for example an empty picture
        frame = None
    if frame is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Image could not be decoded.")
    return frame


# Phone frames sometimes arrive sideways (the camera sensor is landscape while the
# user holds the phone upright). The OpenCV face detector only finds upright faces,
# so every rotation is tried before we accept "no face".
FRAME_ROTATIONS = (
    ("upright", None),
    ("90 clockwise", cv2.ROTATE_90_CLOCKWISE),
    ("90 anticlockwise", cv2.ROTATE_90_COUNTERCLOCKWISE),
    ("180", cv2.ROTATE_180),
)


def detect_emotion(frame):
    """
    Run DeepFace on the frame, retrying the 3 rotations when no face is found.

    Returns (rotated_frame, dominant_emotion, scores) for the first rotation with a
    face, or (frame, None, {}) when no rotation contained a face. A real model or
    input problem is raised to the caller (it is not a "no face" answer).
    """
    for rotation_name, rotate_code in FRAME_ROTATIONS:
        image = frame if rotate_code is None else cv2.rotate(frame, rotate_code)
        try:
            analysis = DeepFace.analyze(img_path=image, actions=["emotion"],
                                        enforce_detection=True, silent=True)
        except ValueError as exc:
            if not str(exc).startswith("Face could not be detected"):
                raise                      # not a missing face: a bad picture for the model
            continue                       # no face in this rotation, try the next one
        result = analysis[0] if isinstance(analysis, list) else analysis
        if rotation_name != "upright":
            logger.info("Face found after rotating the frame %s.", rotation_name)
        return image, result["dominant_emotion"], {name: float(value) for name, value in result["emotion"].items()}
    return frame, None, {}


@router.post("/emotion", response_model=EmotionResponse)
def analyze_emotion(payload: EmotionRequest,
                    current_user: dict = Depends(require_role("student", "teacher"))):
    """Decode a camera frame, run DeepFace, save the picture and the emotion (linked to the session)."""
    # 1. Only into your own, still open session (before decoding images or running the model).
    require_same_user(current_user, payload.user_id)
    check_conn = get_connection()
    try:
        cursor = check_conn.cursor()
        check_session_access(cursor, payload.session_id, current_user)
        require_open_session(cursor, payload.session_id)
    finally:
        check_conn.close()

    # 2. Valid picture? (422 if not; nothing is saved)
    frame = decode_camera_frame(payload.image_base64)
    captured_at = now_utc()

    # 3. Emotion model. "No face" is saved as 'undetected' (the picture exists, the face is missing).
    dominant_emotion = "undetected"
    try:
        saved_frame, emotion, scores = detect_emotion(frame)
    except ValueError:
        logger.warning("DeepFace rejected a frame of session %d", payload.session_id)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Image could not be analysed.")
    except Exception as exc:
        logger.error("DeepFace failed for session %d (%s)", payload.session_id, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Emotion analysis is not available right now.")
    if emotion is None:
        logger.info("No face in the frame of session %d (all 4 rotations tried).", payload.session_id)
    else:
        dominant_emotion = emotion

    # 4. Save the picture (file name only is stored in the database).
    #    The frame is saved in the orientation the face was found in, so the
    #    psychologist review does not show a sideways picture.
    image_name = f"emotion_{payload.user_id}_{payload.session_id}_{captured_at.strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    image_file = os.path.join(settings.EMOTION_IMAGES_DIR, image_name)
    try:
        os.makedirs(settings.EMOTION_IMAGES_DIR, exist_ok=True)
        if not cv2.imwrite(image_file, saved_frame):
            raise OSError("imwrite returned False")
    except Exception as exc:
        logger.error("Could not save emotion image for session %d (%s)", payload.session_id, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save the image.")

    # 5. Save the row. If this fails the picture is deleted again, so no file is left without a row.
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # The server decides the stage from the answers already submitted (the client value is ignored).
        cursor.execute("SELECT ISNULL(MAX(stage_number), 0) FROM Q_Responses WHERE session_id = ?",
                       (payload.session_id,))
        stage_number = min(cursor.fetchone()[0] + 1, MAX_STAGE)
        # question_id is kept only if that question belongs to this stage
        question_id = None
        if payload.question_id is not None:
            cursor.execute("""
                SELECT 1 FROM Q_Questions q INNER JOIN Q_Stages s ON q.stage_id = s.stage_id
                WHERE q.question_id = ? AND s.stage_number = ?""", (payload.question_id, stage_number))
            if cursor.fetchone():
                question_id = payload.question_id

        cursor.execute("""
            INSERT INTO FacialEmotions
                (session_id, dominant_emotion, happy, sad, angry, fear, surprise, disgust, neutral,
                 captured_at, image_path, stage_number, question_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.session_id, dominant_emotion,
             scores.get("happy", 0.0), scores.get("sad", 0.0), scores.get("angry", 0.0),
             scores.get("fear", 0.0), scores.get("surprise", 0.0), scores.get("disgust", 0.0),
             scores.get("neutral", 0.0), captured_at, image_name, stage_number, question_id))
        conn.commit()
        logger.info("Emotion captured: session=%d stage=%d dominant=%s",
                    payload.session_id, stage_number, dominant_emotion)
    except Exception as exc:
        conn.rollback()
        logger.error("FacialEmotions insert failed for session %d (%s)", payload.session_id, type(exc).__name__)
        try:
            os.remove(image_file)
        except OSError:
            pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save the emotion.")
    finally:
        conn.close()

    return EmotionResponse(
        session_id=payload.session_id, dominant_emotion=dominant_emotion,
        scores={k: round(v, 2) for k, v in scores.items()},
        captured_at=captured_at)


@router.get("/emotion/{emotion_id}/image")
def get_emotion_image(emotion_id: int, current_user: dict = Depends(get_current_user)):
    """Return the saved camera picture. Only the session owner or the assigned psychologist may see it."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id, image_path FROM FacialEmotions WHERE emotion_id = ?", (emotion_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")
        check_session_access(cursor, row.session_id, current_user, allow_assigned_psychologist=True)
        image_path = row.image_path
    finally:
        conn.close()

    # Only the file name is used, and only inside the emotion images folder.
    file_path = os.path.join(settings.EMOTION_IMAGES_DIR, os.path.basename(image_path)) if image_path else None
    if not file_path or not os.path.isfile(file_path):
        logger.warning("Emotion image file missing for emotion_id=%d", emotion_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")
    return FileResponse(file_path, media_type="image/jpeg")
