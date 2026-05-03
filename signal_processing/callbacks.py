from database import get_connection

# Map matching your emotion_preprocessor.py
EMOTION_DISTRESS_MAP = {
    "happy": 0.0, "neutral": 0.1, "surprise": 0.2, "undetected": 0.3,
    "disgust": 0.4, "fear": 0.7, "sad": 0.7, "angry": 0.8
}

def get_closest_emotion(session_id: int, window_end_dt) -> float:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT TOP 1 dominant_emotion FROM FacialEmotions 
            WHERE session_id = ? AND captured_at <= ?
            ORDER BY captured_at DESC
        """, (session_id, window_end_dt))
        row = c.fetchone()
        if not row: return 0.3 # default undetected
        return EMOTION_DISTRESS_MAP.get(row[0].lower(), 0.3)
    except Exception:
        return 0.3
    finally:
        conn.close()

def get_questionnaire_score(session_id: int) -> float:
    conn = get_connection()
    try:
        c = conn.cursor()
        # Sum of weights answered so far in Q_Responses
        c.execute("""
            SELECT SUM(q.weight) 
            FROM Q_Responses r
            JOIN Q_Questions q ON r.question_id = q.question_id
            WHERE r.session_id = ? AND r.cal_score > 0
        """, (session_id,))
        row = c.fetchone()
        return float(row[0]) if row and row[0] else 0.0
    except Exception:
        return 0.0
    finally:
        conn.close()
