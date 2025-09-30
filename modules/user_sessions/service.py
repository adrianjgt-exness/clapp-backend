from .model import SessionData
from config import logger, redis_client


class SessionService:
    @staticmethod
    async def create_session(session_data: SessionData, session_token: str) -> bool:
        """Creates a new session in Redis with the provided data structure."""
        session_key = f"session:{session_token}"
        session_payload = session_data.model_dump_json()
        try:
            await redis_client.set(session_key, session_payload, ex=86400)
            logger.info(f"Created Redis session for user: {session_data.user.email}")
            return True
        except Exception as e:
            logger.error(
                f"Failed to create Redis session for {session_data.user.email}: {e}",
                exc_info=True,
            )
            return False

    @staticmethod
    async def get_session(session_token: str) -> SessionData | None:
        """Retrieves a full user session from Redis."""
        session_key = f"session:{session_token}"
        try:
            session_payload = await redis_client.get(session_key)
            if session_payload:
                return SessionData.model_validate_json(session_payload)
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve Redis session: {e}", exc_info=True)
            return None

    @staticmethod
    async def update_cache(session_token: str, cache_key: str, data: dict) -> bool:
        """Adds or completely overwrites a specific key in the session's cache."""
        session = await SessionService.get_session(session_token)
        if not session:
            return False

        session.cache[cache_key] = data
        session_key = f"session:{session_token}"
        session_payload = session.model_dump_json()

        try:
            await redis_client.set(session_key, session_payload, ex=86400)
            logger.info(
                f"Updated cache for key '{cache_key}' in session {session_token[:8]}..."
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to update Redis cache for session {session_token[:8]}: {e}",
                exc_info=True,
            )
            return False

    @staticmethod
    async def delete_from_cache(session_token: str, cache_key: str) -> bool:
        """Deletes a specific key from the session's cache."""
        session = await SessionService.get_session(session_token)
        if not session or cache_key not in session.cache:
            return False

        del session.cache[cache_key]
        session_key = f"session:{session_token}"
        session_payload = session.model_dump_json()

        try:
            await redis_client.set(session_key, session_payload, ex=86400)
            logger.info(
                f"Deleted key '{cache_key}' from session {session_token[:8]}..."
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to delete from Redis cache for session {session_token[:8]}: {e}",
                exc_info=True,
            )
            return False

    @staticmethod
    async def delete_session(session_token: str) -> bool:
        """Deletes an entire user session from Redis (logout)."""
        session_key = f"session:{session_token}"
        try:
            result = await redis_client.delete(session_key)
            return result > 0
        except Exception as e:
            logger.error(f"Failed to delete Redis session: {e}", exc_info=True)
            return False


session_service = SessionService()
