from fastapi import APIRouter, Body, HTTPException, Path, status

from .model import QuestionReportCreate, ReportRequest
from .service import QuestionReportService
from config import logger
from modules.questions.service import QuestionService

router = APIRouter(prefix="/question_reports", tags=["Question Reports"])


@router.post(
    "/{question_id}/report",
    status_code=status.HTTP_201_CREATED,
    summary="Report a problematic question",
    description=(
        "**What this does:** Lets a user flag a question that is unclear, incorrect, or broken. "
        "It records the report and (when possible) immediately fetches a **replacement question** "
        "so the user can continue the test without being blocked.\n\n"
        "**You provide:**\n"
        "• The `question_id` you’re reporting (path parameter).\n"
        "• A short JSON body with your `user_id`, the `test_id`, and a `comment` explaining the issue.\n\n"
        "**You get:**\n"
        "• A confirmation message, and\n"
        "• A `replacement_question` (if available for the same `test_id`)."
    ),
    responses={
        201: {
            "description": "Report saved. Replacement question may be included.",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Question reported successfully.",
                        "replacement_question": {
                            "question_id": "Q-98765",
                            "test_id": "TEST-42",
                            "text": "What is the capital of France?",
                            "options": {
                                "A": "Paris",
                                "B": "London",
                                "C": "Berlin",
                                "D": "Madrid",
                            },
                            "type": "single-choice",
                        },
                    }
                }
            },
        },
        404: {
            "description": "Question not found or cannot be reported.",
            "content": {
                "application/json": {
                    "example": {"detail": "Question Q-12345 not found."}
                }
            },
        },
        500: {
            "description": "Unexpected error while processing the report.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to process question report."}
                }
            },
        },
    },
)
async def report_question(
    question_id: str = Path(
        ...,
        title="Question ID",
        description="The exact ID of the question you want to report.",
    ),
    request: ReportRequest = Body(
        ...,
        title="Report details",
        description="Identify the user and test, and briefly describe the problem you encountered.",
        examples=[
            {
                "minimal": {
                    "summary": "Typical report body",
                    "value": {
                        "user_id": "u_123",
                        "test_id": "TEST-42",
                        "comment": "Option C is correct but marked wrong.",
                    },
                }
            }
        ],
    ),
):
    """
    Handles the reporting of a question during a test.
    It creates a report, hides the question, and returns a suitable replacement.
    """
    try:
        # 1. Create the report document
        report_payload = QuestionReportCreate(
            question_id=question_id,
            user_id=request.user_id,
            test_id=request.test_id,
            comment=request.comment,
        )
        await QuestionReportService.create_report(report_payload)

        # 2. Get a replacement question
        replacement_question = await QuestionService.report_and_replace_question(
            original_question_id=question_id,
            test_id=request.test_id,
            reported_by=request.user_id,
            report_comment=request.comment,
        )

        return {
            "message": "Question reported successfully.",
            "replacement_question": replacement_question,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing report for question {question_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to process question report."
        )
