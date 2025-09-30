# hibob/controller.py
from fastapi import APIRouter, HTTPException, Path
from pydantic import EmailStr

from .model import HibobEmployee
from .service import HibobService
from config import logger


router = APIRouter(prefix="/hibob", tags=["HiBob"])


@router.get(
    "/find/{email}",
    response_model=list[HibobEmployee],
    summary="Find employee(s) by corporate email",
    description=(
        "**What this does:** Looks up staff in HiBob by their corporate email address and returns matching records.\n\n"
        "**You provide:** One email (must be a valid address).\n"
        "**You get:** A list of employees with their name, title, org units (team/department/division/company), photo URL, and timestamps.\n\n"
        "If no employee is found, this returns **404 Not Found** with a friendly message."
    ),
    responses={
        200: {
            "description": "One or more matching employees.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "employee_id": "emp_001234",
                            "employee_code": "EX-56789",
                            "first_name": "Ana",
                            "last_name": "Pereira",
                            "middle_name": None,
                            "display_name": "Ana Pereira",
                            "job_title": "Training Specialist",
                            "email": "ana.pereira@exness.com",
                            "photo": "https://hibob.example/photos/emp_001234.jpg",
                            "team": {
                                "hris_org_unit_id": "TEAM-45",
                                "name": "Training Ops",
                                "is_archived": False,
                                "level": 3,
                            },
                            "department": {
                                "hris_org_unit_id": "DEPT-9",
                                "name": "TQA",
                                "is_archived": False,
                                "level": 2,
                            },
                            "division": {
                                "hris_org_unit_id": "DIV-2",
                                "name": "Operations",
                                "is_archived": False,
                                "level": 1,
                            },
                            "company": {
                                "hris_org_unit_id": "CO-1",
                                "name": "Exness",
                                "is_archived": False,
                                "level": 0,
                            },
                            "created_at": "2025-07-21T14:36:00Z",
                            "checksum": "c387f4c143b44a36",
                        }
                    ]
                }
            },
        },
        404: {
            "description": "No employee with that email.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "No employee found in HiBob with email 'someone@exness.com'."
                    }
                }
            },
        },
        422: {"description": "Invalid email format (validation error)."},
        500: {"description": "Unexpected server error while communicating with HiBob."},
    },
)
async def find_hibob_employee(
    email: EmailStr = Path(
        ...,
        title="Corporate email",
        description="The exact Exness email to search in HiBob.",
        examples={"sample": {"summary": "Example", "value": "ana.pereira@exness.com"}},
    ),
):
    """
    Finds an employee in HiBob by their email address.
    This endpoint is publicly accessible for testing.
    """

    logger.info(f"[HIBOB_CTRL] Searching for HiBob employee '{email}'.")

    employees = await HibobService.find_employee_by_email(email)

    if not employees:
        logger.warning(f"[HIBOB_CTRL] No HiBob employee found for email: {email}")
        raise HTTPException(
            status_code=404,
            detail=f"No employee found in HiBob with email '{email}'.",
        )

    return employees
