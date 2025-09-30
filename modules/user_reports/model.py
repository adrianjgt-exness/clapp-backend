from datetime import datetime
from typing import Literal

from bson import ObjectId
from pydantic import BaseModel, Field


class UserReport(BaseModel):
    """
    Pydantic model for a user report document stored in MongoDB.
    The 'report_type' is optional and is set by an admin.
    """

    id: str = Field(alias="_id", default_factory=lambda: str(ObjectId()))
    user_id: str
    description: str
    report_type: Literal["bug", "feature", "question"] | None = None
    jira_key: str | None = None
    comment: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    status: Literal["Pending Review", "Acknowledged", "In Progress", "Resolved"] = (
        "Pending Review"
    )

    jira_status: str | None = None
    jira_summary: str | None = None
    jira_url: str | None = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }


class UserReportCreate(BaseModel):
    """
    Schema for creating a new user report via the API.
    The user only provides a description.
    """

    description: str


class UserReportAdminUpdate(BaseModel):
    """
    Schema for admins to update a report, primarily to set its type
    or add an internal comment.
    """

    report_type: Literal["bug", "feature", "question"]
    comment: str | None = None


class UserReportAnswer(BaseModel):
    """
    Schema for providing an answer to a report of type 'question'.
    """

    answer: str


class UserReportCreateRequest(BaseModel):
    """
    Schema for the request body when a user creates a new report.
    The frontend sends the user_id, which it has from login.
    """

    user_id: str
    description: str


class JiraLinkPayload(BaseModel):
    """
    Schema for the request body of the PATCH /user-reports/{id}/link endpoint.
    """

    jira_key: str | None = None
    create_new: bool = False


class BulkLinkPayload(BaseModel):
    """
    Schema for the bulk-linking endpoint.
    """

    report_ids: list[str]
    jira_key: str


class JiraCreatePayload(BaseModel):
    report_ids: list[str]
    issue_type: str
    summary: str
    description: str | None = None


class UserReportsResponse(BaseModel):
    reports: list[UserReport]
    total_count: int
