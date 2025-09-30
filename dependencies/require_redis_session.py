from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import redis_client
from modules.user_sessions.model import SessionData

bearer_scheme = HTTPBearer()


async def require_redis_session(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    A dependency that ensures a user session token is valid by checking Redis.
    Returns the full session data (including user profile and cache) if valid.
    """
    token = creds.credentials
    session_key = f"session:{token}"

    session_payload = await redis_client.get(session_key)

    if not session_payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Optional: Extend session lifetime on activity
    await redis_client.expire(session_key, 86400)

    try:
        session_data = SessionData.model_validate_json(session_payload)
        # Return the data as a dictionary for compatibility with other dependencies
        return session_data.model_dump(by_alias=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid session data structure: {e}",
        )
