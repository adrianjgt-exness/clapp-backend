from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DisputeStatus(str, Enum):
    """
    Workflow status of a dispute:
    - Received: newly submitted, not yet reviewed
    - In Progress: assigned and being worked on
    - Resolved: completed with a resolution
    """

    RECEIVED = "Received"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"


class Dispute(BaseModel):
    """
    A dispute raised by an employee to flag unclear, incorrect, or outdated content.

    Minimal fields:
    - department: where the submitter works (for routing/triage)
    - reason: why the content is wrong or unclear
    - user_id: who submitted it

    Optional:
    - proposed_change: suggestion to fix/improve
    - attachments: screenshots or files supporting the case

    Workflow metadata is handled by reviewers:
    - status: moves from Received → In Progress → Resolved
    - resolver_id: who owns the case
    - resolution: what was changed/decided
    """

    # Form fields
    department: str = Field(
        ...,
        description="Submitting employee’s department",
        examples=["QA", "Support", "Training"],
    )
    dispute_type: str = Field(
        ..., description="Seminar quiz, Monthly quiz, Simulation, Pop quiz"
    )
    question_reference: str = Field(
        ..., description="Question number or text being disputed"
    )
    reason: str = Field(
        ...,
        description="Why the question is wrong / unclear",
        examples=["Ambiguous question text in step 3."],
    )
    proposed_change: str | None = Field(
        None,
        description="Suggested fix or improvement.",
        examples=["Clarify expected action and add an example."],
    )
    attachments: list[str] | None = Field(
        default_factory=list, description="Screenshot URLs or file names"
    )

    user_id: str = Field(..., description="The ID of the user who raised the dispute")

    # Workflow metadata
    status: DisputeStatus = Field(
        default=DisputeStatus.RECEIVED,
        description='Workflow status. One of: "Received", "In Progress", "Resolved".',
        examples=["Received"],
    )
    resolver_id: str | None = Field(
        None,
        description="ID of the person currently handling the dispute.",
        examples=["user_456"],
    )
    resolution: str | None = Field(
        None,
        description="Final decision or change that resolves the dispute.",
        examples=["Question text updated; answer key fixed."],
    )

    date_of_creation: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the dispute was created (UTC).",
        examples=["2025-08-15T12:00:00Z"],
    )
    date_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last time the dispute was modified (UTC).",
        examples=["2025-08-15T12:00:00Z"],
    )
