import traceback

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from .model import (
    ChangelogEntry,
    Question,
    ReportAndReplaceRequest,
    ReportAndReplaceResponse,
    StatisticsFilters,
)
from .service import QuestionService
from config import logger
from dependencies import require_admin, require_redis_session, require_role

router = APIRouter(prefix="/questions", tags=["Questions"])


@router.post(
    "",
    summary="Add one or more questions",
    description=(
        "**What this does:** Stores new questions in the database so they become available in tests.\n\n"
        "**Who can use it:** Signed-in users.\n\n"
        "**You provide:** A list of questions (see model in the right panel).\n"
        "**You get:** A confirmation message. When a single question is added, the response includes the new `_id`."
    ),
    responses={
        200: {
            "description": "Question(s) added.",
            "content": {
                "application/json": {
                    "examples": {
                        "single": {
                            "summary": "Single",
                            "value": {
                                "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                                "message": "Question added successfully",
                            },
                        },
                        "multiple": {
                            "summary": "Multiple",
                            "value": {"message": "2 questions added successfully"},
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid question format."},
        401: {"description": "Not signed in."},
        500: {"description": "Internal error while adding questions."},
    },
)
async def create_questions(
    questions: list[Question], current_user: dict = Depends(require_redis_session)
):
    """
    API endpoint to add one or more questions.
    The response message changes based on the number of questions added.
    """
    try:
        # The service function returns a list of the new question IDs
        inserted_ids = await QuestionService.add_questions(questions)

        # Return a specific, helpful message based on the outcome
        if len(inserted_ids) == 1:
            return {"_id": inserted_ids[0], "message": "Question added successfully"}
        elif len(inserted_ids) > 1:
            return {
                "_ids": inserted_ids,
                "message": f"{len(inserted_ids)} questions added successfully",
            }
        else:
            # This case occurs if an empty list was sent
            raise HTTPException(
                status_code=400, detail="No questions were provided to add."
            )

    except Exception as e:
        logger.error(f"Error creating questions: {e}")
        logger.error(traceback.format_exc())
        # Re-raise exceptions that are not handled as HTTPExceptions
        if not isinstance(e, HTTPException):
            raise HTTPException(
                status_code=500,
                detail="An internal server error occurred while adding questions.",
            )
        raise e


@router.get(
    "",
    summary="List questions (admin)",
    description=(
        "**What this does:** Returns a paginated list of questions for review and maintenance.\n\n"
        "**Who can use it:** Admins.\n\n"
        "**You get:** `data`, `page`, `page_size`, and `count`."
    ),
    responses={
        200: {
            "description": "Page of questions.",
            "content": {
                "application/json": {
                    "example": {
                        "data": [
                            {
                                "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                                "stem": "What is the capital of France?",
                                "answers": {
                                    "A": "Paris",
                                    "B": "London",
                                    "C": "Berlin",
                                    "D": "Madrid",
                                },
                                "correct_answer": ["A"],
                                "question_type": "single-choice",
                                "domain": "Geography",
                                "impact_level": "Low",
                                "roles": ["KM"],
                                "status": "Active",
                            }
                        ],
                        "page": 1,
                        "page_size": 50,
                        "count": 1,
                    }
                }
            },
        },
        401: {"description": "Not signed in."},
        403: {"description": "Admin only."},
        500: {"description": "Internal error."},
    },
)
async def get_questions(
    admin_user: dict = Depends(require_admin),
    page: int = Query(1, ge=1, title="Page", description="1-based page number."),
    page_size: int = Query(
        50,
        ge=1,
        le=100,
        title="Page size",
        description="How many items per page (max 100).",
    ),
):
    """API endpoint to retrieve paginated questions from MongoDB"""
    try:
        data, total = await QuestionService.get_questions(page, page_size)
        return {"data": data, "page": page, "page_size": page_size, "count": total}
    except Exception as e:
        logger.exception(f"Error calling get_questions service: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "/my",
    summary="My questions",
    description=(
        "**What this does:** Lists only the questions that belong to the signed-in user (owner).\n\n"
        "**Who can use it:** Signed-in users.\n\n"
        "**You get:** `data`, `page`, `page_size`, and `count`."
    ),
    responses={
        200: {
            "description": "Page of your questions.",
            "content": {
                "application/json": {
                    "example": {
                        "data": [
                            {
                                "_id": "665...",
                                "stem": "Question text...",
                                "status": "Active",
                            }
                        ],
                        "page": 1,
                        "page_size": 50,
                        "count": 1,
                    }
                }
            },
        },
        401: {"description": "Not signed in."},
        500: {"description": "Internal error."},
    },
)
async def get_my_questions(
    current_user_data: dict = Depends(require_redis_session),
    page: int = Query(1, ge=1, title="Page"),
    page_size: int = Query(50, ge=1, le=100, title="Page size"),
):
    """
    API endpoint to retrieve paginated questions owned by the
    currently authenticated user.
    """
    try:
        # Extract the user's ID from the session data.
        # The user's profile is nested under the 'user' key.
        user_profile = current_user_data.get("user")
        if not user_profile or "_id" not in user_profile:
            raise HTTPException(
                status_code=403, detail="Could not identify user from session."
            )

        owner_id = user_profile["_id"]

        # Call the new service function with the owner's ID
        data, total = await QuestionService.get_my_questions(owner_id, page, page_size)

        return {"data": data, "page": page, "page_size": page_size, "count": total}
    except Exception as e:
        logger.exception(f"Error calling get_my_questions service: {e}")
        # Re-raise HTTPExceptions to preserve status codes
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "/active/count",
    summary="How many active questions exist?",
    description=(
        "**What this does:** Returns a single number: the total count of questions that are currently marked as active.\n\n"
        "**Who can use it:** Signed-in users."
    ),
    responses={
        200: {
            "description": "Count of active questions.",
            "content": {
                "application/json": {"example": {"active_questions_count": 1240}}
            },
        },
        401: {"description": "Not signed in."},
        500: {"description": "Internal error."},
    },
)
async def get_active_question_count(
    current_user: dict = Depends(require_redis_session),
):
    """
    API endpoint to get the total count of active questions.
    """
    try:
        count = await QuestionService.get_active_questions_count()
        return {"active_questions_count": count}
    except Exception as e:
        logger.exception(f"Error in /count/active endpoint: {e}")
        raise HTTPException(
            status_code=500,
            detail="An error occurred while counting active questions.",
        )


@router.get(
    "/{question_id}/changelog",
    response_model=list[ChangelogEntry],
    summary="See the change history of a question",
    description=(
        "**What this does:** Shows who changed what on a specific question over time.\n\n"
        "**Who can use it:** Signed-in users.\n\n"
        "**You get:** A list of changes (field, old value, new value), each with a version and timestamp."
    ),
    responses={
        200: {
            "description": "Changelog entries.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "version": 2,
                            "updated_at": "2025-08-20T10:00:00Z",
                            "changes": [
                                {
                                    "field": "stem",
                                    "old_value": "Old text",
                                    "new_value": "New text",
                                }
                            ],
                        },
                        {
                            "version": 3,
                            "updated_at": "2025-08-22T09:12:00Z",
                            "changes": [
                                {
                                    "field": "correct_answer",
                                    "old_value": ["B"],
                                    "new_value": ["A"],
                                }
                            ],
                        },
                    ]
                }
            },
        },
        401: {"description": "Not signed in."},
        404: {"description": "Question not found."},
        500: {"description": "Internal error."},
    },
)
async def get_question_changelog(
    question_id: str = Path(
        ...,
        title="Question ID",
        description="The exact question you want the history for.",
    ),
    current_user: dict = Depends(require_redis_session),
):
    """
    API endpoint to retrieve the changelog for a specific question.
    """
    try:
        changelog = await QuestionService.get_question_changelog(question_id)
        return changelog
    except Exception as e:
        logger.exception(f"Error getting changelog for question {question_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while retrieving the changelog.",
        )


@router.get(
    "/statistics",
    summary="Question statistics",
    description=(
        "**What this does:** Returns aggregated statistics about questions (cached for performance).\n\n"
        "**Who can use it:** Signed-in users.\n\n"
        "**You provide:** Optional filters (see query params on the right).\n"
        "**You get:** A `statistics` object with totals/aggregations relevant to the selected filters."
    ),
    responses={
        200: {
            "description": "Aggregated statistics.",
            "content": {
                "application/json": {
                    "examples": {
                        "minimal": {"summary": "Minimal", "value": {"total": 120}},
                        "byBuckets": {
                            "summary": "With buckets",
                            "value": {
                                "total": 120,
                                "byImpactLevel": {"High": 10, "Medium": 40, "Low": 70},
                                "byStatus": {"Active": 100, "Hidden": 20},
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Not signed in."},
        500: {"description": "Internal error."},
    },
)
async def get_question_statistics(
    filters: StatisticsFilters = Depends(),
    current_user: dict = Depends(require_redis_session),
):
    """
    API endpoint to retrieve question statistics.
    It uses a caching mechanism to avoid recalculating statistics on every call.
    """
    try:
        stats_data = await QuestionService.get_question_statistics(filters.model_dump())
        # The service returns the full DB document; we extract the nested 'statistics'
        # object which is what the frontend component expects.
        if stats_data is not None:
            if isinstance(stats_data, dict):
                return stats_data.get("statistics", {})
            elif isinstance(stats_data, list):
                # Return the list or handle as needed
                return stats_data
            else:
                return {}
        else:
            return {}
    except Exception as e:
        logger.exception(f"Error in statistics endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.put(
    "/{question_id}",
    summary="Update a question",
    description=(
        "**What this does:** Replaces the question with updated content (text, answers, metadata).\n\n"
        "**Who can use it:** Users with the **Training and Quality** role.\n\n"
        "**You provide:** The `question_id` and a full `Question` payload.\n"
        "**You get:** The updated record (shape depends on the database layer)."
    ),
    responses={
        200: {
            "description": "Question updated.",
            "content": {
                "application/json": {"example": {"_id": "665...", "message": "Updated"}}
            },
        },
        401: {"description": "Not signed in."},
        403: {"description": "Requires Training and Quality role."},
        404: {"description": "Question not found."},
        500: {"description": "Internal error."},
    },
)
async def update_question(
    question_id: str = Path(..., title="Question ID"),
    updated_data: Question = Body(..., title="Updated question"),
    current_user: dict = Depends(require_role(allowed_roles=["Training and Quality"])),
):
    """Updates a specific question by its ID"""
    try:
        return await QuestionService.update_question(question_id, updated_data)
    except Exception as e:
        logger.exception(f"Error updating question {question_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post(
    "/{question_id}/report-and-replace",
    response_model=ReportAndReplaceResponse,
    status_code=status.HTTP_200_OK,
    summary="Report a broken/unclear question and keep going",
    description=(
        "**What this does:**\n"
        "1) Marks the reported question as hidden,\n"
        "2) Creates a report with your comment, and\n"
        "3) Tries to find a **replacement question** for the same test so you can continue without being blocked.\n\n"
        "**Who can use it:** Signed-in users.\n\n"
        "**You provide:** Path `question_id` and a short JSON body (see example).\n"
        "**You get:** Confirmation plus a replacement question if one is available. "
        "If no perfect match is found, the system gradually relaxes the match criteria and tells you which dimensions were relaxed."
    ),
    responses={
        200: {
            "description": "Report recorded. Replacement returned when available.",
            "content": {
                "application/json": {
                    "example": {
                        "reported_question_id": "Q-12345",
                        "report_id": "6660cafe...",
                        "replacement_found": True,
                        "relaxed_dimensions": [],
                        "message": "Replacement found",
                        "replacement": {
                            "id": "Q-98765",
                            "test_id": "TEST-42",
                            "stem": "What is the capital of France?",
                            "answers": {
                                "A": "Paris",
                                "B": "London",
                                "C": "Berlin",
                                "D": "Madrid",
                            },
                            "question_type": "single-choice",
                            "domain": "Geography",
                            "impact_level": "Low",
                            "status": "Active",
                            "isReplacement": True,
                            "reporting_disabled": True,
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid body (e.g., missing `report_comment`)."},
        401: {"description": "Not signed in."},
        404: {"description": "Question not found."},
        500: {"description": "Internal error."},
    },
)
async def report_and_replace_question(
    question_id: str = Path(..., title="Question ID"),
    body: ReportAndReplaceRequest = Body(
        ...,
        title="Report details",
        description="Identify the test and include a short comment. You may exclude specific question IDs from replacement.",
        examples=[
            {
                "summary": "Typical report",
                "value": {
                    "test_id": "TEST-42",
                    "reported_by": "u_123",  # optional (taken from session if available)
                    "report_comment": "Image missing; cannot answer.",
                    "exclude_question_ids": ["Q-55555"],  # optional
                },
            }
        ],
    ),
    current_user: dict = Depends(require_redis_session),
):
    """
    Reports a question and fetches a replacement.

    Steps:
    1. Marks reported question as Hidden.
    2. Creates a question report with the user’s comment.
    3. Finds a replacement matching strict filters; progressively relaxes if needed.
    4. Returns structured response for frontend.
    """
    try:
        user_profile = current_user.get("user") or {}
        reported_by = user_profile.get("_id")
        if not reported_by:
            reported_by = body.reported_by

        payload = await QuestionService.report_and_replace_question(
            original_question_id=question_id,
            test_id=body.test_id,
            reported_by=body.reported_by or "",
            report_comment=body.report_comment,
            exclude_question_ids=body.exclude_question_ids,
        )
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in report-and-replace for question {question_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
