import hashlib
import json
from typing import Any

from .service import jira_service
from config import redis_client
from config.logger import logger

TTL = 15 * 60  # 15 minutes


def _make_key(prefix: str, identifier: str) -> str:
    h = hashlib.sha1(identifier.encode()).hexdigest()
    return f"{prefix}:{h}"


async def _safe_redis_get(key: str) -> str | None:
    """Return cached string or None; never raise."""
    if not redis_client:
        return None
    try:
        return await redis_client.get(key)
    except Exception as e:
        logger.warning(f"Redis GET failed for key '{key}': {e}")
        return None


async def _safe_redis_set(key: str, value: str, ex: int) -> None:
    """Best-effort cache write; never raise."""
    if not redis_client:
        return
    try:
        await redis_client.set(key, value, ex=ex)
    except Exception as e:
        logger.warning(f"Redis SET failed for key '{key}': {e}")


async def cached_search_all_issues(jql: str) -> list[dict[str, Any]]:
    key = _make_key("jira:search", jql)

    # Try cache
    raw = await _safe_redis_get(key)
    if raw:
        try:
            logger.info("Cache hit for JQL search")
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Cache decode failed (search): {e}. Fetching fresh.")

    # Fallback to Jira
    logger.info("Cache miss for JQL search, fetching from Jira")
    data = await jira_service.search_all_issues(jql, max_results=500)

    # Best-effort write-back
    try:
        await _safe_redis_set(key, json.dumps(data, separators=(",", ":")), ex=TTL)
    except Exception:
        # Already logged inside _safe_redis_set
        pass

    return data


async def cached_get_first_issue(jql: str) -> dict[str, Any] | None:
    key = _make_key("jira:first", jql)

    # Try cache
    raw = await _safe_redis_get(key)
    if raw:
        try:
            logger.info("Cache hit for first-issue search")
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Cache decode failed (first-issue): {e}. Fetching fresh.")

    # Fallback to Jira
    logger.info("Cache miss for first-issue, fetching from Jira")
    issue = await jira_service.get_first_issue(jql)

    # Best-effort write-back (store dict or None as JSON)
    try:
        await _safe_redis_set(key, json.dumps(issue, separators=(",", ":")), ex=TTL)
    except Exception:
        # Already logged inside _safe_redis_set
        pass

    return issue
