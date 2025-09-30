from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Answer(BaseModel):
    """
    Represents a user's answer to a single question.
    """

    question_id: str
    selected_options: list[Any]  # Can be a list of strings, numbers, etc.
    confidence_level: str | None = None


class TestResultCreate(BaseModel):
    """
    This model represents the payload sent from the frontend when a user submits a test.
    """

    user_id: str
    test_id: str
    started_at: datetime | None = None
    answers: list[Answer]
    flagged_questions: list[str] = Field(default_factory=list)
    reported_questions: list[str] = Field(default_factory=list)
    time_spent_seconds: int


class TestResultInDB(TestResultCreate):
    """
    This model represents the full test result document as it is stored in the database.
    It includes backend-calculated fields like timestamps and the final score.
    """

    started_at: datetime = Field(default_factory=datetime.now)
    submitted_at: datetime = Field(default_factory=datetime.now)
    score_percent: float = 0.0
    status: str = "completed"

    class Config:
        from_attributes = True
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
