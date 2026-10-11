# ============================================================
# models/questionnaire_models.py — Pydantic schemas for Q&A
# ============================================================

from pydantic import BaseModel, field_validator
from typing import List, Optional


class QuestionnaireAnswer(BaseModel):
    """A single question-answer pair submitted by the patient."""

    question_id: int
    response_choice: int   # 0-4 (Never ... Always). A numeric string such as "3" is accepted too.
    cal_score: Optional[float] = None   # Ignored: the server calculates choice * question weight

    @field_validator("response_choice", mode="before")
    @classmethod
    def choice_must_be_0_to_4(cls, value):
        """Accept an int 0-4 or a numeric string '0'..'4'. Labels such as 'Often' are rejected."""
        if isinstance(value, bool):
            raise ValueError("response_choice must be a number from 0 to 4")
        if isinstance(value, str) and value.strip() in ("0", "1", "2", "3", "4"):
            value = int(value.strip())
        if isinstance(value, int) and 0 <= value <= 4:
            return value
        raise ValueError("response_choice must be a number from 0 to 4")


class SubmitStageRequest(BaseModel):
    """Request body for POST /questionnaire/submit."""

    session_id: int
    stage_number: int
    answers: List[QuestionnaireAnswer]


class SubmitStageResponse(BaseModel):
    """
    Response body for POST /questionnaire/submit.
    'passed' indicates whether the stage threshold was met.
    'next_stage' is None when all stages are complete.
    """

    stage_number: int
    total_score: float
    passed: bool
    next_stage: Optional[int] = None
    message: str


class StageInfo(BaseModel):
    """Minimal stage metadata returned by GET /questionnaire/stages."""

    stage_id: int
    stage_number: int
    stage_name: str
    target_role: str
    threshold: float


class QuestionInfo(BaseModel):
    """Single question returned by GET /questionnaire/questions/{stage}."""

    question_id: int
    stage_id: int
    question_text: str
    weight: float
