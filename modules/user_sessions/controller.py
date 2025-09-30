from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException

from .model import SessionData
from .service import session_service
from dependencies.require_session_token import require_session_token

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("/me", response_model=SessionData)
async def get_current_user_session(token: str = Depends(require_session_token)):
    """
    Retrieves the current user's full session data, including the cache,
    using the session token.
    """
    session_data = await session_service.get_session(token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session_data


@router.patch("/me/cache/{cache_key}")
async def update_session_cache(
    cache_key: str,
    data: Dict[str, Any] = Body(...),
    token: str = Depends(require_session_token),
):
    """
    Adds or overwrites a specific key in the user's session cache.
    This is the generic endpoint for saving any in-progress work.
    """
    success = await session_service.update_cache(token, cache_key, data)
    if not success:
        raise HTTPException(
            status_code=404, detail="Session not found or failed to update cache"
        )
    return {"status": "success", "message": f"Cache key '{cache_key}' updated."}


@router.delete("/me/cache/{cache_key}")
async def delete_from_session_cache(
    cache_key: str,
    token: str = Depends(require_session_token),
):
    """
    Deletes a specific key from the user's session cache.
    Used when a draft is finalized and saved to the database.
    """
    success = await session_service.delete_from_cache(token, cache_key)
    if not success:
        raise HTTPException(
            status_code=404, detail=f"Session or cache key '{cache_key}' not found"
        )
    return {"status": "success", "message": f"Cache key '{cache_key}' deleted."}


@router.post("/logout")
async def logout(token: str = Depends(require_session_token)):
    """Logs the user out by deleting their entire session."""
    await session_service.delete_session(token)
    return {"status": "success", "message": "Logged out successfully."}
