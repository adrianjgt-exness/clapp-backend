from fastapi import APIRouter, HTTPException, Query

from .model import (
    BulkLinkPayload,
    JiraCreatePayload,
    JiraLinkPayload,
    UserReport,
    UserReportAdminUpdate,
    UserReportAnswer,
    UserReportCreate,
    UserReportCreateRequest,
    UserReportsResponse,
)
from .service import UserReportService
from config import logger

router = APIRouter(prefix="/user-reports", tags=["User Reports"])


@router.post("", response_model=UserReport, status_code=201)
async def create_user_report(report_request: UserReportCreateRequest):
    """
    Creates a new user report. The user ID is sent from the frontend,
    which is aware of the logged-in user.
    """
    try:
        report_data = UserReportCreate(description=report_request.description)
        new_report = await UserReportService.create_report(
            user_id=report_request.user_id, report_data=report_data
        )
        return new_report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create report: {e}")


@router.get("", response_model=UserReportsResponse)
async def get_user_reports(
    user_id: str | None = Query(None, description="Filter reports by user ID."),
    report_type: str | None = Query(None, description="Filter by report type."),
    jira_key: str | None = Query(None, description="Filter by Jira key."),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Lists user reports with pagination and filtering.
    Admins can see all reports; users can filter by their own user_id.
    """
    reports_data = await UserReportService.get_reports(
        page, limit, user_id, report_type, jira_key
    )
    return reports_data


@router.patch("/{report_id}", response_model=UserReport)
async def update_report_by_admin(report_id: str, update_data: UserReportAdminUpdate):
    """
    Admin-only endpoint to categorize a report or add a comment.
    """
    updated_report = await UserReportService.admin_update_report(report_id, update_data)
    if not updated_report:
        raise HTTPException(status_code=404, detail="Report not found")
    return updated_report


@router.patch("/{report_id}/link", status_code=200)
async def link_report_to_jira(report_id: str, payload: JiraLinkPayload):
    """
    Links a single report to an existing or new Jira issue.
    """
    try:
        if payload.create_new:
            jira_key = await UserReportService.create_new_jira_issue(
                report_ids=[report_id]
            )
            return {"status": "success", "jira_key": jira_key}
        elif payload.jira_key:
            await UserReportService.link_to_jira(
                report_ids=[report_id], jira_key=payload.jira_key
            )
            return {"status": "success", "jira_key": payload.jira_key}
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'jira_key' or 'create_new: true' must be provided.",
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to link to Jira: {e}")


@router.post("/bulk-link", status_code=200)
async def bulk_link_reports_to_jira(payload: BulkLinkPayload):
    """
    Links multiple reports to a single existing Jira issue.
    """
    try:
        result = await UserReportService.link_to_jira(
            report_ids=payload.report_ids, jira_key=payload.jira_key
        )
        return {"status": "success", "modified_count": result["modified_count"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bulk link to Jira: {e}")


@router.post("/bulk-create-jira", status_code=201)
async def bulk_create_jira_issue(payload: JiraCreatePayload):
    """
    Creates a new Jira issue with a custom summary and description,
    and links the given user reports to it.
    """
    try:
        description = payload.description if payload.description is not None else ""
        jira_key = await UserReportService.create_jira_issue_from_reports(
            report_ids=payload.report_ids,
            issue_type=payload.issue_type,
            summary=payload.summary,
            description=description,
        )
        return {"status": "success", "jira_key": jira_key}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to bulk create Jira issue: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to create and link Jira issue."
        )


@router.patch("/{report_id}/answer", response_model=UserReport)
async def answer_user_question(report_id: str, answer: UserReportAnswer):
    """
    Admin-only endpoint to answer a question-type report, which resolves it.
    """
    resolved_report = await UserReportService.answer_question(report_id, answer)
    if not resolved_report:
        raise HTTPException(status_code=404, detail="Report not found")
    return resolved_report
