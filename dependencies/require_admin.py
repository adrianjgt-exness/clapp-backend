from fastapi import Depends, HTTPException

from .require_redis_session import require_redis_session
from config import logger


async def require_admin(current_user_data: dict = Depends(require_redis_session)):
    """
    Checks if the user is an admin by inspecting the nested user profile
    within the session data.
    """
    logger.info("Checking for administrator access.")

    user_profile = current_user_data.get("user")
    if not user_profile or not user_profile.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return current_user_data
