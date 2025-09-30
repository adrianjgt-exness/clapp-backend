from typing import Any

from pydantic import BaseModel, Field

from modules.users.model import UserProfile


class SessionData(BaseModel):
    """
    Represents the complete data structure for a user session stored in Redis.
    """

    # The user's core profile, fetched once from MongoDB upon login.
    user: UserProfile

    # A flexible dictionary to store any in-progress work (drafts, etc.).
    # The keys will be dynamic (e.g., "question_cache", "test_draft_123").
    # The values can be any JSON-serializable data.
    cache: dict[str, Any] = Field(default_factory=dict)
