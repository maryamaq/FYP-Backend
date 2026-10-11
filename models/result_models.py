"""models/result_models.py — Pydantic schemas for MH results."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ScoreBreakdown(BaseModel):
    """Detailed score breakdown for a session result."""
    emotional: float = 0.0
    functional: float = 0.0
    context: float = 0.0
    isolation: float = 0.0
    critical: Optional[float] = None
    # None = not measured / not available (never 0)
    questionnaire_score: Optional[float] = None
    physio_score: Optional[float] = None
    eeg_stress_index: Optional[float] = None
    hr_mean: Optional[float] = None
    bp_avg_systolic: Optional[float] = None
    bp_systolic_delta: Optional[float] = None
    dominant_emotion: Optional[str] = None
    emotion_distress: float = 0.0


class UnreliableModality(BaseModel):
    """A signal whose stored value cannot be trusted, with the reason."""
    name: str
    reason: str


class AppointmentInfo(BaseModel):
    """The psychologist appointment linked to a session."""
    appointment_id: int
    psychologist_name: str
    status: str


class SessionResult(BaseModel):
    """Full mental health result for one session."""
    session_id: int
    user_id: Optional[int] = None
    user_role: Optional[str] = None
    recommendation: str
    referral_note: Optional[str] = None
    confidence: float = 0.0
    final_score: float
    score_breakdown: ScoreBreakdown
    session_duration_minutes: Optional[float] = None
    calculated_at: Optional[datetime] = None
    # Added fields (older apps simply ignore them)
    tier: str = "Low"                                   # Low | Medium | High (display only)
    missing_modalities: List[str] = []                  # signals that were not measured
    unreliable_modalities: List[UnreliableModality] = []
    advisor_notified: bool = False
    appointment: Optional[AppointmentInfo] = None
    legacy: bool = False                                # saved before the data checks existed


class UserHistoryItem(BaseModel):
    """Summary of a single past session."""
    session_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    recommendation: Optional[str] = None
    final_score: Optional[float] = None
    calculated_at: Optional[datetime] = None


class UserHistory(BaseModel):
    """Ordered list of past sessions for a user."""
    user_id: int
    sessions: List[UserHistoryItem]
    # None = no completed assessment yet (never a made-up date)
    next_due_date: Optional[datetime] = None
    due_status: Optional[str] = None                    # e.g. "due now" / "due in 5 days"
