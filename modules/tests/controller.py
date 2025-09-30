from fastapi import APIRouter, HTTPException, Query, status

from config import logger
from modules.tests.model import (
    TestCreate,
    TestFinalizeRequest,
    TestInDB,
    TestInvitationRequest,
    TestUpdate,
)
from modules.tests.service import TestService

router = APIRouter(prefix="/tests", tags=["Tests"])


@router.post("/create-draft", status_code=status.HTTP_201_CREATED, response_model=dict)
async def create_test_draft(test_data: TestCreate):
    """
    Creates a new test in a 'draft' state.
    Relies on the TestCreate model for validation.
    """
    try:
        test_id = await TestService.create_draft(test_data)
        return {"testId": test_id, "message": "Test draft created successfully"}
    except Exception as e:
        logger.error(f"Error creating test draft: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create test draft.",
        )


@router.get("", response_model=list[TestInDB])
async def get_tests(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    created_by: str | None = Query(
        None, description="Filter tests by creator's user ID"
    ),
):
    """
    Retrieves a paginated list of tests.
    """
    try:
        tests = await TestService.get(
            page=page, page_size=page_size, created_by=created_by
        )
        return tests
    except Exception as e:
        logger.error(f"Error getting tests: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tests.",
        )


@router.get("/assigned")
async def get_assigned_tests(user_id: str = Query(...)):
    """
    Retrieves all tests assigned to a specific user, identified by user_id.
    The frontend is expected to provide the user_id from its local storage.
    """
    if not user_id:
        raise HTTPException(
            status_code=400, detail="A user_id must be provided as a query parameter."
        )

    try:
        tests = await TestService.get_assigned_tests_for_user(user_id)
        return tests
    except Exception as e:
        logger.error(f"Error fetching assigned tests for user {user_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve assigned tests."
        )


@router.get("/{test_id}", response_model=TestInDB)
async def get_test_by_id(test_id: str):
    """
    Retrieves a single test by its unique ID.
    """
    try:
        test = await TestService.get_by_id(test_id)
        if not test:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Test not found"
            )
        return test
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error getting test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve test.",
        )


@router.put("/{test_id}", status_code=status.HTTP_200_OK, response_model=dict)
async def update_test(test_id: str, test_data: TestUpdate):
    """
    Updates the basic details of a test.
    """
    try:
        success = await TestService.update(test_id, test_data)
        if not success:
            logger.warning(f"Update for test {test_id} resulted in no changes.")
        return {"message": "Test updated successfully"}
    except Exception as e:
        logger.error(f"Error updating test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update test.",
        )


@router.post(
    "/{test_id}/invitations", status_code=status.HTTP_200_OK, response_model=dict
)
async def save_test_invitations(test_id: str, invitation_data: TestInvitationRequest):
    """
    Saves the list of users invited to a test.
    """
    try:
        success = await TestService.save_invitations(
            test_id, invitation_data.invited_users
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test not found or invitations unchanged.",
            )
        return {"message": "Invitations saved successfully."}
    except Exception as e:
        logger.error(f"Error saving invitations for test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save invitations.",
        )


@router.post("/{test_id}/finalize", status_code=status.HTTP_200_OK, response_model=dict)
async def finalize_test(test_id: str, finalize_data: TestFinalizeRequest):
    """
    Finalizes a test by applying a template and changing its status.
    """
    try:
        success = await TestService.finalize(test_id, finalize_data)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to finalize test. Ensure test and template IDs are valid.",
            )
        return {"success": True, "message": "Test finalized successfully."}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error finalizing test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during test finalization.",
        )


@router.delete("/{test_id}", status_code=status.HTTP_200_OK, response_model=dict)
async def delete_test(test_id: str):
    """
    Deletes a test by its ID.
    """
    try:
        success = await TestService.delete(test_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Test not found."
            )
        return {"message": "Test deleted successfully."}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error deleting test {test_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete test.",
        )


@router.get("/stats/open-tests-count", response_model=dict)
async def get_open_tests_count_for_user(user_id: str):
    """
    Retrieves the count of tests in "Open" status for a specific user.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="A user_id must be provided.")
    try:
        count = await TestService.count_open_tests_for_user(user_id)
        return {"open_tests_count": count}
    except Exception as e:
        logger.error(f"Error counting open tests for user {user_id}: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve open test count."
        )
