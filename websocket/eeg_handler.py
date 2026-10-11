"""websocket/eeg_handler.py — WebSocket that pushes live EEG data to the Flutter app.

HOW IT WORKS:
  The Flutter app connects to WS /ws/eeg/{session_id}.
  This handler loops every 2 seconds and pushes the latest processed
  EEG values (alpha, beta, theta, stress_index) from the EEGStream object.

  The EEGStream (hardware/eeg_stream.py) runs in a separate thread,
  continuously reading from the Muse headset via BlueMuse/LSL and
  computing band powers. This handler just reads its .latest dict
  and forwards it to the phone over WebSocket.

  If EEG is not connected, we push a "disconnected" status so the
  Flutter app can show a "Connect EEG" prompt.
"""

import json
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from database import get_connection
from hardware.eeg_stream import get_eeg_stream
from utils.auth_utils import decode_token, check_session_access

logger = logging.getLogger(__name__)

WS_POLICY_VIOLATION = 1008   # standard WebSocket close code for "not allowed"


def _is_session_owner(session_id: int, token: str) -> bool:
    """True only if the token is valid, belongs to a student/teacher, and owns this session."""
    try:
        current_user = decode_token(token)
        if current_user["role"] not in ("student", "teacher"):
            return False
        conn = get_connection()
        try:
            check_session_access(conn.cursor(), session_id, current_user)
        finally:
            conn.close()
        return True
    except HTTPException:
        return False
    except Exception as exc:
        logger.error("WebSocket auth check failed: %s", exc)
        return False


async def eeg_websocket_handler(websocket: WebSocket, session_id: int, token: str = "") -> None:
    """
    Push live EEG snapshot data to the Flutter app every 2 seconds.
    The app shows this in the Live Vitals panel during a session.
    The JWT is passed as ?token=... because the WebSocket client cannot set headers easily.
    """
    if not _is_session_owner(session_id, token):
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info("EEG WebSocket connected: session_id=%d", session_id)

    try:
        while True:
            stream = get_eeg_stream(session_id)

            if stream is None:
                # No stream started yet — waiting for /eeg/connect call
                payload = {
                    "connected": False,
                    "status": "idle",
                    "pulse_rate": None,
                    "message": "Press Connect EEG to begin.",
                }
            else:
                latest = stream.get_latest()
                # 'connected' is only true after a snapshot was really saved.
                payload = {
                    "connected":  latest["connected"],
                    "status":     latest["status"],
                    "message":    latest["message"],
                    "pulse_rate": latest["pulse_rate"],     # number, or null = no pulse measured
                }
                if latest["connected"]:
                    payload.update({
                        "alpha":        latest["alpha"],
                        "beta":         latest["beta"],
                        "theta":        latest["theta"],
                        "stress_index": latest["stress_index"],
                        "question_num": latest.get("question_num"),
                        "timestamp":    datetime.now(timezone.utc).isoformat(),
                    })

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2.0)   # push every 2 seconds

    except WebSocketDisconnect:
        logger.info("EEG WebSocket disconnected: session_id=%d", session_id)
    except Exception as exc:
        logger.exception("EEG WebSocket error (session=%d): %s", session_id, exc)
