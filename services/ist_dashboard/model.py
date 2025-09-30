from datetime import datetime

from pydantic import BaseModel


class Issue(BaseModel):
    id: str
    key: str
    summary: str
    status: str
    resolved: datetime
    epic_link: str
    assignee: str
    assignee_email: str | None = None
    description: str


class Epic(BaseModel):
    id: str
    key: str
    summary: str
    status: str


class DuplicateResult(BaseModel):
    original: str
    duplicate: str
    message_link: str
