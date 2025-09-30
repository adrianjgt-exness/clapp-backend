from typing import Any

from pydantic import BaseModel, Field


class JiraIssueCreate(BaseModel):
    """
    Schema for creating a new Jira issue. The project key is often
    fixed, but the summary, description, and issue type are required.
    """

    summary: str = Field(
        ...,
        description="The summary or title of the issue.",
        examples=["Enable CSV export"],
    )
    description: str = Field(
        ...,
        description="The detailed description of the issue.",
        examples=["Allow trainers to export results as CSV for auditing."],
    )
    issue_type: str = Field(
        default="Task",
        description="The type of the issue (e.g., 'Bug', 'Story', 'Task').",
        examples=["Task"],
    )


class JiraIssueEdit(BaseModel):
    """
    Schema for editing an existing Jira issue. All fields are optional,
    so only provided fields will be updated.
    """

    summary: str | None = Field(
        None, description="New short title.", examples=["Export results to CSV"]
    )
    description: str | None = Field(
        None, description="Revised description or extra context."
    )
    assignee_id: str | None = Field(
        None, description="Jira account ID to assign the issue to."
    )


class JiraTransitionPayload(BaseModel):
    """
    Schema for the payload required to transition a Jira issue.
    You need to provide the ID of the target transition.
    """

    transition_id: int = Field(
        ...,
        description="The transition ID from the 'See allowed status changes' endpoint.",
        examples=["31"],
    )


# --- Response Models ---


class JiraTransition(BaseModel):
    """Represents an available transition for a Jira issue."""

    id: str = Field(..., description="Internal transition ID.", examples=["31"])
    name: str = Field(
        ..., description="Friendly name shown in Jira.", examples=["Resolve Issue"]
    )


class JiraIssueResponse(BaseModel):
    """A simplified representation of a Jira issue for API responses."""

    id: str = Field(..., description="Internal Jira ID.", examples=["10025"])
    key: str = Field(
        ..., description="Public issue key used in URLs.", examples=["CLAPP-125"]
    )
    self_url: str = Field(
        alias="self",
        description="Link to the issue in Jira.",
        examples=["https://jira.example/browse/CLAPP-125"],
    )
    fields: dict[str, Any] = Field(
        ..., description="Raw fields sent by Jira (status, assignee, etc.)."
    )


class JiraDropdownIssue(BaseModel):
    """A minimal representation of a Jira issue for dropdowns."""

    key: str = Field(..., description="Issue key.", examples=["CLAPP-101"])
    summary: str = Field(
        ..., description="Short title.", examples=["Enable Google Sign-In"]
    )
