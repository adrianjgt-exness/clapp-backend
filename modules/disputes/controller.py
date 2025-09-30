from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from .model import Dispute, DisputeStatus
from .service import DisputeService
from config import logger

router = APIRouter(prefix="/disputes", tags=["Disputes"])


@router.post(
    "",
    summary="Submit a new dispute",
    description=(
        "**What this does:** Records a dispute raised by an employee about training content, "
        "tests, or process materials.\n\n"
        "**You provide:** A Dispute form (department, reason, optional proposed change/attachments, and your user ID).\n"
        "**You get:** The new dispute ID and a confirmation message."
    ),
    responses={
        200: {
            "description": "Dispute accepted.",
            "content": {
                "application/json": {
                    "example": {
                        "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                        "message": "Dispute received",
                    }
                }
            },
        },
        500: {"description": "Could not store the dispute."},
    },
)
async def submit_dispute(dispute: Dispute):
    try:
        dispute_id = await DisputeService.create_dispute(dispute)
        return {"_id": dispute_id, "message": "Dispute received"}
    except Exception as e:
        logger.exception(f"Failed to store dispute: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "",
    summary="List disputes",
    description=(
        "**What this does:** Returns disputes with optional status filter and pagination.\n\n"
        "**You provide:**\n"
        "• `status` (optional): filter by workflow status.\n"
        "• `page` (default 1) and `page_size` (default 50, max 100).\n\n"
        "**You get:** An array of dispute records plus paging info."
    ),
    responses={
        200: {
            "description": "Page of disputes.",
            "content": {
                "application/json": {
                    "example": {
                        "data": [
                            {
                                "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                                "department": "QA",
                                "reason": "Question text is ambiguous on step 3.",
                                "proposed_change": "Clarify expected action and provide example.",
                                "attachments": [
                                    "https://clapp.test.env/api/disputes/attachment/1a2b3c"
                                ],
                                "user_id": "user_123",
                                "status": "Received",
                                "resolver_id": None,
                                "resolution": None,
                                "date_of_creation": "2025-08-15T12:00:00Z",
                                "date_updated": "2025-08-15T12:00:00Z",
                            }
                        ],
                        "page": 1,
                        "page_size": 50,
                        "count": 1,
                    }
                }
            },
        },
        500: {"description": "Could not load disputes."},
    },
)
async def get_disputes(
    status: DisputeStatus | None = Query(
        None,
        title="Status filter",
        description='Filter by workflow status. One of: "Received", "In Progress", "Resolved".',
        examples={
            "received": {"value": "Received"},
            "in_progress": {"value": "In Progress"},
            "resolved": {"value": "Resolved"},
        },
    ),
    page: int = Query(1, ge=1, title="Page number", description="1-based page index."),
    page_size: int = Query(
        50, ge=1, le=100, title="Items per page", description="Max 100."
    ),
):
    try:
        data = await DisputeService.list_disputes(status, page, page_size)
        return {
            "data": data,
            "page": page,
            "page_size": page_size,
            "count": len(data),
        }
    except Exception as e:
        logger.exception(f"Failed to load disputes: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get(
    "/stats",
    summary="Dispute counts by status",
    description=(
        "**What this does:** Provides a quick overview of how many disputes are at each step.\n\n"
        "**You get:** A small JSON object keyed by status."
    ),
    responses={
        200: {
            "description": "Counts by status.",
            "content": {
                "application/json": {
                    "example": {"Received": 12, "In Progress": 5, "Resolved": 8}
                }
            },
        }
    },
)
async def dispute_stats():
    counts = await DisputeService.get_status_counts()
    return counts


@router.put(
    "/{dispute_id}/take",
    summary="Take ownership of a dispute",
    description=(
        "**What this does:** Assigns yourself (or a resolver) to a dispute and moves it to *In Progress*.\n\n"
        '**You provide:** Path param `dispute_id` and JSON body `{ "resolver_id": "..." }`.\n'
        "**You get:** The updated record or a confirmation object."
    ),
    responses={
        200: {
            "description": "Ownership taken.",
            "content": {
                "application/json": {
                    "example": {
                        "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                        "status": "In Progress",
                        "resolver_id": "user_456",
                    }
                }
            },
        },
        400: {"description": "`resolver_id` missing."},
        500: {"description": "Could not update dispute."},
    },
)
async def take_ownership(dispute_id: str, payload: dict):
    resolver_id = payload.get("resolver_id")
    if not resolver_id:
        raise HTTPException(status_code=400, detail="resolver_id required")
    try:
        return await DisputeService.take_ownership(dispute_id, resolver_id)
    except Exception as e:
        logger.exception(f"Failed to take ownership of {dispute_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.put(
    "/{dispute_id}/resolve",
    summary="Resolve a dispute",
    description=(
        "**What this does:** Marks the dispute as *Resolved* and records the resolution note.\n\n"
        '**You provide:** Path param `dispute_id` and JSON body `{ "resolver_id": "...", "resolution": "..." }`.\n'
        "**You get:** The updated record or a confirmation object."
    ),
    responses={
        200: {
            "description": "Dispute resolved.",
            "content": {
                "application/json": {
                    "example": {
                        "_id": "665f2c9b1a2b3c4d5e6f7a8b",
                        "status": "Resolved",
                        "resolver_id": "user_456",
                        "resolution": "Question wording updated and retested.",
                    }
                }
            },
        },
        400: {"description": "`resolver_id` and `resolution` are required."},
        500: {"description": "Could not resolve dispute."},
    },
)
async def resolve_dispute(dispute_id: str, payload: dict):
    resolver_id = payload.get("resolver_id")
    resolution = payload.get("resolution")
    if not resolver_id or not resolution:
        raise HTTPException(
            status_code=400, detail="resolver_id and resolution required"
        )
    try:
        return await DisputeService.resolve_dispute(dispute_id, resolver_id, resolution)
    except Exception as e:
        logger.exception(f"Failed to resolve dispute {dispute_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post(
    "/upload-files",
    summary="Upload attachments for a dispute",
    description=(
        "**What this does:** Accepts one or more files (screenshots, evidence) and stores them in Google Drive.\n\n"
        "**You provide:** `multipart/form-data` with field name `files` containing 1..N files.\n"
        "**You get:** A list of file URLs you can save in the dispute."
    ),
    responses={
        200: {
            "description": "Files uploaded.",
            "content": {
                "application/json": {
                    "example": {
                        "file_urls": [
                            "https://clapp.test.env/api/disputes/attachment/1a2b3c",
                            "https://clapp.test.env/api/disputes/attachment/4d5e6f",
                        ]
                    }
                }
            },
        },
        400: {"description": "No files were uploaded."},
        500: {"description": "File upload failed."},
    },
)
async def upload_dispute_files(files: list[UploadFile] = File(...)):
    """
    Accepts file uploads and passes them to the service for storage in Google Drive.
    Returns a list of URLs for the uploaded files.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    try:
        # Call the new service function to handle the upload
        file_links = await DisputeService.upload_dispute_attachments(files)
        return {"file_urls": file_links}
    except Exception as e:
        logger.exception(f"Failed to upload files: {e}")
        raise HTTPException(status_code=500, detail="File upload failed.")


@router.get(
    "/attachment/{file_id}",
    summary="Fetch an attachment (proxied)",
    description=(
        "**What this does:** Streams a file from Google Drive to the browser to avoid CORS issues.\n\n"
        "**You provide:** `file_id` (internal Drive identifier).\n"
        "**You get:** The file content streamed to your browser. "
        "_Current implementation serves image content; future enhancement will detect and set the exact MIME type._"
    ),
    responses={
        200: {"description": "Attachment stream (image)."},
        500: {"description": "Could not retrieve attachment."},
    },
)
async def get_attachment_proxy(file_id: str):
    """
    Acts as a proxy to fetch image attachments from Google Drive, avoiding CORS issues.
    """
    try:
        # Get the async generator from the service
        file_stream = await DisputeService.get_dispute_attachment(file_id)

        # Use a StreamingResponse to send the file content back to the client
        # We don't know the media type here, so we let the browser infer it.
        # For a more robust solution, you could store the mimetype with the attachment link.
        return StreamingResponse(
            file_stream, media_type="image/png"
        )  # Assuming PNG, adjust if needed
    except Exception as e:
        logger.exception(f"Failed to proxy attachment {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve attachment.")
