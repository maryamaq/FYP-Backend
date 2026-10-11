# ============================================================
# models/session_models.py — Pydantic schemas for Sessions
# ============================================================

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class StartSessionRequest(BaseModel):
    """Request body for POST /session/start."""

    user_id: int


class StartSessionResponse(BaseModel):
    """Response body for POST /session/start."""

    session_id: int
    started_at: datetime


class EndSessionRequest(BaseModel):
    """Request body for POST /session/end."""

    session_id: int
    user_id: int


class EndSessionResponse(BaseModel):
    """Response body for POST /session/end with scoring results."""

    session_id: int
    recommendation: str      # 'Normal' | 'Calm Down' | 'See Psychologist' | 'Emergency'
    referral_note: Optional[str] = None
    final_score: float
    confidence: float        # not computed, always 0.0
    ended_at: datetime
    risk_class: Optional[str] = None                 # stored label, e.g. 'Healthy'
    missing_modalities: List[str] = []               # signals that were not measured


class SessionDetailResponse(BaseModel):
    """Full session details returned by GET /session/{session_id}."""

    session_id: int
    user_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str
    eeg_count: int = 0       # Number of EEG readings collected
    bp_count: int = 0        # Number of BP readings collected
    emotion_count: int = 0   # Number of emotion frames processed
    questionnaire_stages: int = 0  # Number of questionnaire stages completed
