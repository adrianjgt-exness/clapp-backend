from fastapi import APIRouter, Depends, HTTPException, Query, status
import httpx

from .model import (
    JiraDropdownIssue,
    JiraIssueCreate,
    JiraIssueEdit,
    JiraIssueResponse,
    JiraTransition,
    JiraTransitionPayload,
)
from .service import jira_service
from config import logger
from dependencies.require_admin import require_admin

router = APIRouter(
    prefix="/jira",
    tags=["Jira"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "/active-issues",
    response_model=list[JiraDropdownIssue],
    summary="Active CLAPP issues (lightweight list)",
    description=(
        "**What this does:** Returns a compact list of currently active Jira issues "
        "for the CLAPP project, meant for dropdowns and quick selectors.\n\n"
        "**Why it matters:** It lets anyone pick an issue by its key and short title "
        "without wading through full Jira details.\n\n"
        "**You provide:** Nothing.\n"
        "**You get:** A list like `[{'key': 'CLAPP-123', 'summary': 'Short title'}, ...]`."
    ),
    responses={
        200: {
            "description": "List of active, lightweight issues ready for UI dropdowns.",
            "content": {
                "application/json": {
                    "example": [
                        {"key": "CLAPP-101", "summary": "Enable Google Sign-In"},
                        {
                            "key": "CLAPP-109",
                            "summary": "Improve training reports export",
                        },
                    ]
                }
            },
        },
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
)
async def get_active_clapp_issues():
    """
    Gets a list of active issues from the CLAPP project that are not
    in 'Done' or 'Cancelled' status, suitable for a dropdown list.
    """
    jql = (
        'project = CLAPP AND status not in ("Done", "Cancelled") '
        'AND issuetype not in ("Task","Epic") ORDER BY created DESC'
    )
    try:
        issues = await jira_service.search_all_issues(jql)
        return [
            JiraDropdownIssue(key=issue["key"], summary=issue["fields"]["summary"])
            for issue in issues
        ]
    except HTTPException:
        # propagate service-level HTTPExceptions (e.g. 502)
        raise
    except Exception:
        logger.error("Error fetching active CLAPP issues", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve active CLAPP issues",
        )


@router.get(
    "/issues",
    response_model=list[JiraIssueResponse],
    summary="Search Jira issues (by a simple rule)",
    description=(
        "**What this does:** Finds Jira issues that match a search rule written in JQL "
        "(Jira Query Language). If you’re not technical, think of JQL as a filter.\n\n"
        "**You provide:** A simple rule, e.g. "
        '`project = CLAPP AND status = "In Progress"`.\n'
        "**You get:** A list of matching issues with key info you can read and share."
    ),
    responses={
        200: {
            "description": "Matching issues.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "10001",
                            "key": "CLAPP-120",
                            "self": "https://jira.example/browse/CLAPP-120",
                            "fields": {
                                "summary": "Add SSO for internal users",
                                "status": {"name": "In Progress"},
                                "assignee": {"displayName": "Jane Doe"},
                            },
                        }
                    ]
                }
            },
        },
        400: {"description": "The search rule (JQL) was missing or invalid."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
)
async def search_jira_issues(
    jql: str = Query(
        ...,
        title="Search rule (JQL)",
        description=(
            "A simple rule that filters issues. Examples:\n"
            '• `project = CLAPP AND status = "To Do"`\n'
            "• `assignee = currentUser()`\n"
            '• `text ~ "training"`'
        ),
        examples={
            "byStatus": {
                "summary": "By status",
                "value": 'project = CLAPP AND status = "In Progress"',
            },
            "myIssues": {
                "summary": "Issues assigned to me",
                "value": "assignee = currentUser()",
            },
            "containsWord": {
                "summary": "Mentions 'training'",
                "value": 'project = CLAPP AND text ~ "training"',
            },
        },
    ),
):
    """
    Search for issues with a human-readable filter.
    Search for Jira issues using a JQL query.
    Example: `project = CLAPP AND status = "In Progress"`
    """
    try:
        raw = await jira_service.search_all_issues(jql)
        return [
            JiraIssueResponse(
                id=item["id"],
                key=item["key"],
                self=item["self"],
                fields=item.get("fields", {}),
            )
            for item in raw
        ]
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error searching Jira issues with JQL: {jql}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search operation failed",
        )


@router.post(
    "/issues",
    response_model=JiraIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Jira issue",
    description=(
        "**What this does:** Opens a brand-new issue in Jira for CLAPP work.\n\n"
        "**Who can use it:** Admins only.\n\n"
        "**You provide:** A short title, a clear description, and the type of work "
        "(Task, Bug, etc.).\n"
        "**You get:** The created issue with its key (e.g. `CLAPP-125`)."
    ),
    responses={
        201: {
            "description": "Issue created.",
            "content": {
                "application/json": {
                    "example": {
                        "id": "10025",
                        "key": "CLAPP-125",
                        "self": "https://jira.example/browse/CLAPP-125",
                        "fields": {
                            "summary": "Add export to CSV",
                            "issuetype": {"name": "Task"},
                        },
                    }
                }
            },
        },
        400: {"description": "Missing or invalid fields (e.g., empty summary)."},
        403: {"description": "Not allowed (admin-only endpoint)."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
    tags=["Jira", "Admin"],
    dependencies=[Depends(require_admin)],
)
async def create_jira_issue(issue_data: JiraIssueCreate):
    """Create an issue with a clear title and description people can act on."""
    try:
        new_issue = await jira_service.create_issue(
            summary=issue_data.summary,
            description=issue_data.description,
            issue_type=issue_data.issue_type,
        )
        return JiraIssueResponse(
            id=new_issue["id"],
            key=new_issue["key"],
            self=new_issue["self"],
            fields={},  # fields aren’t returned on create
        )
    except HTTPException:
        raise
    except Exception:
        logger.error("Error creating Jira issue", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Issue creation failed",
        )


@router.patch(
    "/issues/{issue_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Edit an existing issue",
    description=(
        "**What this does:** Updates the issue’s title, description, or assignee.\n\n"
        "**Who can use it:** Admins only.\n\n"
        "**You provide:** The issue key (e.g. `CLAPP-120`) and what to change.\n"
        "**You get:** No content back—just confirmation via the status code."
    ),
    responses={
        204: {"description": "Issue updated."},
        400: {"description": "Nothing to update or invalid change."},
        403: {"description": "Not allowed (admin-only endpoint)."},
        404: {"description": "Issue not found."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
    tags=["Jira", "Admin"],
    dependencies=[Depends(require_admin)],
)
async def edit_jira_issue(issue_key: str, update_data: JiraIssueEdit):
    """
    Edit an existing Jira issue's summary or description.
    """
    try:
        await jira_service.edit_issue(issue_key, update_data)
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error editing Jira issue {issue_key}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Issue update failed",
        )


@router.get(
    "/issues/{issue_key}/transitions",
    response_model=list[JiraTransition],
    summary="See allowed status changes for an issue",
    description=(
        "**What this does:** Shows the status changes (transitions) that are allowed "
        "right now for a given issue—e.g., from *In Progress* to *Done*.\n\n"
        "**You provide:** The issue key (e.g. `CLAPP-120`).\n"
        "**You get:** A list of possible next steps with their IDs and friendly names."
    ),
    responses={
        200: {
            "description": "Allowed transitions.",
            "content": {
                "application/json": {
                    "example": [
                        {"id": "21", "name": "Start Progress"},
                        {"id": "31", "name": "Resolve Issue"},
                    ]
                }
            },
        },
        404: {"description": "Issue not found."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
)
async def get_issue_transitions(issue_key: str):
    """
    Get the list of available workflow transitions for an issue.
    Answer: “What can we move this issue to, right now?”
    """
    try:
        return await jira_service.get_transitions(issue_key)
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error fetching transitions for {issue_key}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transitions",
        )


@router.post(
    "/issues/{issue_key}/transitions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Move an issue to its next status",
    description=(
        "**What this does:** Moves the issue along the workflow (for example, "
        "from *To Do* → *In Progress* → *Done*).\n\n"
        "**Who can use it:** Admins only.\n\n"
        "**You provide:** The issue key and the transition ID you want to apply.\n"
        "**You get:** No content back—just confirmation via the status code."
    ),
    responses={
        204: {"description": "Issue transitioned."},
        400: {"description": "Transition not allowed right now."},
        403: {"description": "Not allowed (admin-only endpoint)."},
        404: {"description": "Issue not found."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
    tags=["Jira", "Admin"],
    dependencies=[Depends(require_admin)],
)
async def transition_jira_issue(issue_key: str, payload: JiraTransitionPayload):
    """
    Transition a Jira issue to a new status (e.g., from 'To Do' to 'In Progress').
    """
    try:
        await jira_service.transition_issue(issue_key, payload.transition_id)
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error transitioning Jira issue {issue_key}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Issue transition failed",
        )


@router.post(
    "/issues/{issue_key}/append-description",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Append a clear note into the description",
    description=(
        "**What this does:** Safely appends a new note into the issue’s description, "
        "keeping existing text intact. If the note includes email addresses, "
        "they are merged into the “Affected users” section to avoid duplicates.\n\n"
        "**Who can use it:** Admins only.\n\n"
        "**You provide:** The issue key and the text to append.\n"
        "**You get:** No content back—just confirmation via the status code."
    ),
    responses={
        204: {"description": "Description updated."},
        400: {"description": "Nothing to append."},
        403: {"description": "Not allowed (admin-only endpoint)."},
        404: {"description": "Issue not found."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
    tags=["Jira", "Admin"],
    dependencies=[Depends(require_admin)],
)
async def append_issue_description(issue_key: str, text_to_append: str):
    """
    Append text to the Jira issue description. If the payload contains the
    'This issue affects the following users:' block, the server will MERGE
    the emails into the existing block (avoiding duplicates).
    """
    try:
        await jira_service.append_to_description(issue_key, text_to_append)
    except httpx.ConnectError as e:
        logger.error(f"Network error appending to {issue_key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to Jira to update description",
        )
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error appending description to {issue_key}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Appending description failed",
        )


@router.post(
    "/issues/{issue_key}/comment",
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to an issue",
    description=(
        "**What this does:** Adds a comment visible on the issue’s discussion thread.\n\n"
        "**Who can use it:** Admins only.\n\n"
        "**You provide:** The issue key and a comment.\n"
        "**You get:** A confirmation that the comment was created."
    ),
    responses={
        201: {"description": "Comment added."},
        400: {"description": "The comment text was missing or invalid."},
        403: {"description": "Not allowed (admin-only endpoint)."},
        404: {"description": "Issue not found."},
        502: {"description": "Could not connect to Jira."},
        500: {"description": "Unexpected server error."},
    },
    tags=["Jira", "Admin"],
    dependencies=[Depends(require_admin)],
)
async def comment_jira_issue(issue_key: str, comment: str):
    """Keep a clean, visible trail of decisions and updates."""
    try:
        await jira_service.add_comment(issue_key, comment)
    except httpx.ConnectError as e:
        # explicit catch if network glitch slips through
        logger.error(f"Network error commenting on {issue_key}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to Jira to post comment",
        )
    except HTTPException:
        raise
    except Exception:
        logger.error(f"Error adding comment to {issue_key}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Adding comment failed",
        )
