from fastapi import APIRouter, HTTPException, Query, status

from .model import TestResultCreate
from .service import TestSessionService
from config import logger

router = APIRouter(prefix="/test-session", tags=["Test Sessions"])


@router.get("/{test_id}/start", response_model=dict)
async def start_test_session(test_id: str, user_id: str = Query(...)):
    """
    Endpoint to start a test session.
    It validates the user's eligibility and returns the test questions,
    which are assembled dynamically by the service layer.
    """
    try:
        session_data = await TestSessionService.get_test_for_session(test_id, user_id)
        return session_data
    except (ValueError, PermissionError) as e:
        logger.warning(f"Failed to start test {test_id} for user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting test session for test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start test session.",
        )


@router.post("/{test_id}/submit", response_model=dict)
async def submit_test_session(test_id: str, session_data: TestResultCreate):
    """
    Endpoint to submit the completed test answers and save the result.
    """
    if test_id != session_data.test_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path test ID does not match payload test ID.",
        )

    try:
        result_id = await TestSessionService.submit_test_results(session_data)
        return {"message": "Test submitted successfully.", "result_id": result_id}
    except ValueError as e:
        logger.warning(
            f"Failed to submit test {test_id} for user {session_data.user_id}: {e}"
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error submitting test results for test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit test results.",
        )


@router.get("/results/{test_id}", response_model=dict)
async def get_test_results(test_id: str):
    """
    Endpoint to get the aggregated results for a specific test.
    """
    try:
        summary_data = await TestSessionService.get_test_results_summary(test_id)
        return summary_data
    except ValueError as e:
        logger.warning(f"Failed to get results for test {test_id}: {e}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve test results.",
        )


@router.get("/result/{result_id}", response_model=dict)
async def get_single_test_result(result_id: str, user_id: str = Query(...)):
    """
    Endpoint for a user to view their own detailed test result.
    """
    try:
        detailed_result = await TestSessionService.get_detailed_result(
            result_id, user_id
        )
        return detailed_result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error getting detailed result {result_id} for user {user_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve detailed test result.",
        )
