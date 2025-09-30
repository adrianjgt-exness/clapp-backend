from fastapi import APIRouter, HTTPException, Request

from .service import OktaService
from config import logger

router = APIRouter(prefix="/frontend-log", tags=["Frontend Logs"])


@router.post(
    "",
    summary="Record a frontend log event",
    description=(
        "**What this does:** Accepts a log event from the web app and forwards it to the backend logger "
        "(whatever the app is configured to use: file, console, aggregator, etc.).\n\n"
        "**You provide:** JSON with a human-readable `message` and an optional `meta` object for context "
        "(e.g., route, user id, browser, component).\n\n"
        '**You get:** A simple confirmation `{ "status": "ok" }` if the log is accepted.'
    ),
    responses={
        200: {
            "description": "Log accepted.",
            "content": {"application/json": {"example": {"status": "ok"}}},
        },
        500: {
            "description": "Server error while recording the log.",
            "content": {
                "application/json": {
                    "example": {"detail": "Failed to start study session"}
                }
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Short, human-readable text you want to appear in the backend logs.",
                            },
                            "meta": {
                                "type": "object",
                                "description": "Optional structured context that will be attached to the log entry.",
                                "additionalProperties": True,
                            },
                        },
                        "required": ["message"],
                    },
                    "examples": {
                        "minimal": {
                            "summary": "Only a message",
                            "value": {"message": "App mounted"},
                        },
                        "withContext": {
                            "summary": "Message with context",
                            "value": {
                                "message": "User clicked Submit",
                                "meta": {
                                    "route": "/quiz/42",
                                    "user_id": "u_123",
                                    "component": "SubmitButton",
                                    "browser": "Chrome 126",
                                    "env": "dev",
                                },
                            },
                        },
                    },
                }
            },
        }
    },
)
async def log_from_frontend(request: Request):
    """
    Receives a log from the frontend and forwards it to the backend logger.
    """
    try:
        status = await OktaService.log_from_frontend(request)
        return status
    except Exception:
        logger.exception("Error calling logger service")
        raise HTTPException(status_code=500, detail="Failed to start study session")
