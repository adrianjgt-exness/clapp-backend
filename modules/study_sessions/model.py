from typing import Union

from pydantic import BaseModel


class StudySessionQuestion(BaseModel):
    question_id: str
    stem: str
    answers: dict
    gkb_link: str | None = None
    question_type: str | None = None


class StudySessionStartResponse(BaseModel):
    questions: list[StudySessionQuestion]


class StudySessionAnswer(BaseModel):
    question_id: str
    selected_option: Union[str, list[str]]
    time_spent_seconds: int | None = None


class StudySessionSubmitRequest(BaseModel):
    user_id: str
    answers: list[StudySessionAnswer]
