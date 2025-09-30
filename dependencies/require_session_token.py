from fastapi import HTTPException, Header


async def require_session_token(authorization: str | None = Header(None)) -> str:
    """
    A dependency that extracts the bearer token string from the Authorization header.
    Raises a 401 HTTPException if the token is missing or invalid.
    This is used for services that need the raw token to operate on session keys.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization.split(" ")[1]
