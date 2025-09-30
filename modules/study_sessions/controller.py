from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from config import logger
from modules.study_sessions.model import (
    StudySessionStartResponse,
    StudySessionSubmitRequest,
)
from modules.study_sessions.service import StudySessionService

router = APIRouter(prefix="/study-session", tags=["Study Sessions"])


@router.post("/start", response_model=StudySessionStartResponse)
async def start_study_session():
    """Start a study session and return 20 random questions."""
    try:
        questions = await StudySessionService.start_session()
        response = StudySessionStartResponse(questions=questions)
        return response
    except ValidationError as ve:
        logger.exception(
            f"Validation error when building StudySessionStartResponse: {ve}"
        )
        raise HTTPException(
            status_code=500, detail="Validation error while starting study session"
        )
    except Exception:
        logger.exception("Error starting study session")
        raise HTTPException(status_code=500, detail="Failed to start study session")


@router.post("/submit")
async def submit_study_session(data: StudySessionSubmitRequest):
    """Submit answers and store the study session result"""
    try:
        result = await StudySessionService.submit_session(data.user_id, data.answers)
        return result
    except Exception:
        logger.exception("Error submitting study session")
        raise HTTPException(status_code=500, detail="Failed to submit study session")
