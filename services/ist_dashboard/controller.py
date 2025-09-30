from fastapi import APIRouter, HTTPException, Query, status

from .model import DuplicateResult, Epic, Issue
from .service import ISTDashboardService
from config import logger

router = APIRouter(prefix="/ist-dashboard", tags=["IST Dashboard"])


@router.get("/epics-inprogress", response_model=list[Epic])
async def list_epics():
    try:
        return await ISTDashboardService.fetch_inprogress_epics()
    except Exception:
        logger.error("Error in /epics-inprogress", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve EPICs in progress",
        )


@router.get("/tasks-done", response_model=list[Issue])
async def list_tasks_done():
    try:
        return await ISTDashboardService.fetch_all_tasks_done()
    except Exception:
        logger.error("Error in /tasks-done", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve completed tasks",
        )


@router.get("/actions-summary", response_model=dict[str, dict[str, int]])
async def actions_summary():
    try:
        return await ISTDashboardService.compute_actions_summary()
    except Exception:
        logger.error("Error in /actions-summary", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not compute actions summary",
        )


@router.post("/cleanup-duplicates", response_model=list[DuplicateResult])
async def cleanup_dups():
    try:
        results = await ISTDashboardService.cleanup_duplicates()
        return results
    except Exception:
        logger.error("Error in /cleanup-duplicates", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Duplicate cleanup failed",
        )


@router.get(
    "/tasks",
    response_model=list[Issue],
    summary="Fetch tasks filtered by region/month/agent",
)
async def get_filtered_tasks(
    region: str = Query(..., description="Region name, e.g. 'SSA Global'"),
    month: str | None = Query(None, description="Full month name, e.g. 'February'"),
    agent: str | None = Query(None, description="Assignee username or e-mail"),
):
    try:
        return await ISTDashboardService.fetch_filtered_tasks(region, month, agent)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching filtered tasks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch filtered tasks",
        )


@router.get(
    "/jira-link",
    response_model=str,
    summary="Get a Jira URL for searching SUPP‐Done issues by region/month/agent",
)
async def get_jira_link(
    region: str = Query(..., description="Region name, e.g. 'SSA Global'"),
    month: str | None = Query(None, description="Full month name, e.g. 'February'"),
    agent: str | None = Query(None, description="Assignee username or e-mail"),
):
    try:
        url = await ISTDashboardService.build_jira_link(region, month, agent)
        return url
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error building Jira link: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build Jira link",
        )


@router.get("/actions-summary-v2", response_model=dict[str, dict[str, int]])
async def actions_summary_v2():
    try:
        return await ISTDashboardService.compute_actions_summary_v2()
    except Exception:
        logger.error("Error in /actions-summary-v2", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not compute actions summary",
        )


@router.get(
    "/jira-link-v2",
    response_model=str,
    summary="Get a Jira URL for searching SUPP‐Done issues by region/month/agent/kind",
)
async def get_jira_link_v2(
    region: str = Query(..., description="Region name, e.g. 'SSA Global'"),
    month: str | None = Query(None, description="Full month name, e.g. 'February'"),
    agent: str | None = Query(None, description="Assignee display name or e-mail"),
    kind: str | None = Query(None, description="Action kind (issue summary text)"),
):
    try:
        url = await ISTDashboardService.build_jira_link_v2(region, month, agent, kind)
        return url
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error building Jira link v2: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build Jira link",
        )
