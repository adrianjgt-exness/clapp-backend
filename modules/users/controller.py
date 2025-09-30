from fastapi import APIRouter, Depends, HTTPException

from .model import UserListItem, UserProfile, UserUpdateRequest
from .service import UserService
from config import logger
from dependencies import require_admin, require_redis_session, require_role

# --- Import the base session dependency and the logger ---

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserProfile)
async def read_users_me(current_user_data: dict = Depends(require_redis_session)):
    """
    Returns the profile of the currently authenticated user from their session.
    """
    user_profile_data = current_user_data.get("user")
    if not user_profile_data:
        raise HTTPException(status_code=404, detail="User profile not found in session")
    return UserProfile(**user_profile_data)


# ---
@router.get("", response_model=list[UserProfile])
async def list_all_users(admin_user: dict = Depends(require_admin)):
    """Lists all users in the database. Requires administrator access."""
    logger.info(
        f"Admin '{admin_user.get('user', {}).get('email')}' is listing all users."
    )
    return await UserService.get_all_users()


@router.get("/list", response_model=list[UserListItem])
async def list_users_for_test(
    current_user: dict = Depends(require_role(allowed_roles=["Training and Quality"])),
):
    """
    Provides a simplified list of users for creating test invitations.
    Requires Training and Quality role.
    """
    logger.info(
        f"User '{current_user.get('user', {}).get('email')}' is fetching the user list for tests."
    )
    return await UserService.get_user_list()


@router.post("/update_role")
async def update_role(
    payload: UserUpdateRequest,
    admin_user: dict = Depends(require_admin),
):
    """Updates a user's role and admin status. Requires administrator access."""
    logger.info(
        f"Admin '{admin_user.get('email')}' is updating user '{payload.user_id}' "
        f"to role='{payload.new_role}', is_admin={payload.is_admin}."
    )
    success = await UserService.update_user_role(
        user_id=payload.user_id,
        new_role=payload.new_role,
        is_admin=payload.is_admin,
    )
    if not success:
        logger.warning(
            f"Failed update for user '{payload.user_id}': User not found or no changes made."
        )
        raise HTTPException(
            status_code=404, detail="User not found or no changes made."
        )
    return {"status": "success", "message": "User role updated."}


@router.get("/roles", response_model=list[str])
async def get_user_roles(current_user: UserProfile = Depends(require_redis_session)):
    """
    Retrieves a list of all unique user roles from the database.
    This is useful for populating dropdowns in the frontend.
    """
    roles = await UserService.get_distinct_user_roles()
    return roles


@router.get("/{user_id}", response_model=UserProfile)
async def get_user_by_id_route(
    user_id: str,
    current_user: dict = Depends(require_redis_session),
):
    """Gets a specific user's profile by their ID. Requires any logged-in user."""
    logger.info(
        f"User '{current_user.get('email')}' is requesting profile for user_id '{user_id}'."
    )
    user = await UserService.get_user_by_id(user_id)
    if not user:
        logger.warning(
            f"User '{current_user.get('email')}' failed to find profile for user_id '{user_id}'."
        )
        raise HTTPException(status_code=404, detail="User not found")
    return user
