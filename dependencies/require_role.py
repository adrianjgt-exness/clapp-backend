from fastapi import Depends, HTTPException

from .require_redis_session import require_redis_session
from config import logger


def require_role(allowed_roles: list[str]):
    """
    A dependency factory that creates a role checker.
    It ensures the user's role is in the list of allowed roles.
    """

    async def role_checker(current_user_data: dict = Depends(require_redis_session)):
        # Access the nested user profile from the session data
        user_profile = current_user_data.get("user")
        if not user_profile:
            raise HTTPException(
                status_code=403, detail="Access denied: Invalid user session."
            )

        # Check if the user has one of the allowed roles
        user_role = user_profile.get("user_role")
        if user_role in allowed_roles:
            logger.info(
                f"Granting access to user with role '{user_role}': {user_profile.get('email')}"
            )
            return current_user_data

        # If the role check fails, deny access
        logger.warning(
            f"Access denied for user {user_profile.get('email')}. "
            f"Role '{user_role}' is not in allowed list: {allowed_roles}."
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. You do not have the required permissions.",
        )

    return role_checker
