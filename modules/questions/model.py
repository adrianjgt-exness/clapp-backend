from datetime import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class Question(BaseModel):
    source: str = Field(
        ..., description="Where this question comes from.", examples=["Update"]
    )
    source_reference: str | None = Field(
        None,
        description="Optional external reference (document ID, ticket, etc.).",
        examples=["DOC-2187"],
    )
    confluence_link: HttpUrl = Field(
        ...,
        description="Link to the source document in Confluence.",
        examples=["https://confluence.example/pages/1234"],
    )
    roles: list[str] = Field(
        ...,
        description="Which roles this question targets.",
        examples=[["KM", "Trainer"]],
    )
    date_of_creation: dt = Field(
        default_factory=dt.now,
        description="When this question was first created (server time).",
    )
    last_updated_at: dt = Field(
        default_factory=dt.now,
        description="When this question was last updated (server time).",
    )
    version: int = Field(
        default=1, description="Version number (increments when updated).", examples=[1]
    )
    owner: str = Field(
        ...,
        description="User ID of the person who owns/created the question.",
        examples=["6866110adc35eb417a0462b4"],
    )
    stem: str = Field(
        ...,
        description="The question text the learner reads.",
        examples=["What is the capital of France?"],
    )
    question_type: str = Field(
        ..., description="Type of question.", examples=["Multiple Choice"]
    )
    answers: dict[str, str] = Field(
        ...,
        description="Options map (keys like A/B/C... to text).",
        examples=[{"A": "Paris", "B": "London", "C": "Berlin", "D": "Madrid"}],
    )
    correct_answer: list[str] = Field(
        ..., description="The correct option keys (one or more).", examples=[["A"]]
    )
    impact_level: str = Field(
        default="",
        description="How critical this question is (e.g., High/Medium/Low).",
        examples=["Low"],
    )
    regions: list[str] = Field(
        ..., description="Relevant regions.", examples=[["MENA", "LATAM"]]
    )
    countries: list[str] = Field(default_factory=list)
    domain: str
    topic: str
    status: str
    points: int = Field(default=1)
    explanation: str = Field(default="")
    tests_used_in: list[str] = Field(default_factory=list)
    changelog: list[dict] = Field(default_factory=list)


class StatisticsFilters(BaseModel):
    domain: str | None = Field(
        "all", description='Filter by domain or "all" for no filter.', examples=["all"]
    )
    topic: str | None = Field(
        "all", description='Filter by topic or "all".', examples=["Payments"]
    )
    impactLevel: str | None = Field(
        "all", description='Filter by impact level or "all".', examples=["High"]
    )
    status: str | None = Field(
        "all", description='Filter by status or "all".', examples=["Active"]
    )
    regions: str | None = Field(
        "all", description='Filter by region(s) or "all".', examples=["LATAM"]
    )
    timeRange: str | None = Field(
        "30",
        description="Time window in days used for statistics (string).",
        examples=["30"],
    )


class QuestionUpdate(BaseModel):
    """
    A model for partial updates, allowing optional fields.
    Used for actions like changing a question's status.
    """

    status: str | None = None
    last_updated_at: dt = Field(default_factory=dt.now)


class ChangeDetail(BaseModel):
    """Defines the structure for a single field change."""

    field: str = Field(..., description="Which field changed.", examples=["stem"])
    old_value: Any = Field(..., description="Value before the change.")
    new_value: Any = Field(..., description="Value after the change.")


class ChangelogEntry(BaseModel):
    """Defines the structure for a single changelog entry."""

    version: int = Field(..., description="Version after the change.", examples=[2])
    updated_at: dt = Field(
        ...,
        description="When the change was made (UTC).",
        examples=["2025-08-20T10:00:00Z"],
    )
    changes: list[ChangeDetail] = Field(
        ..., description="What changed in this version."
    )


# Request from the client
class ReportAndReplaceRequest(BaseModel):
    test_id: str = Field(
        ...,
        description="The test where the issue occurred.",
        examples=["68a93019feccc12ae5074868"],
    )
    reported_by: str | None = Field(
        None,
        description="User ID reporting the issue. If omitted, taken from your session.",
    )
    report_comment: str = Field(
        ...,
        min_length=3,
        description="Short explanation of what's wrong.",
        examples=["Image missing; cannot answer."],
    )
    exclude_question_ids: list[str] = Field(
        default_factory=list,
        description="Question IDs you don't want as replacements.",
        examples=[["68af58d262d8b92758701355"]],
    )


# Returned to the client
class ReplacementQuestionOut(BaseModel):
    # Mirror your existing QuestionOut schema; include key fields.
    # Add client-only flags so UI disables re-reporting.
    id: str = Field(..., description="Replacement question ID.")
    topic: str | None = Field(None, description="Topic (if defined).")
    impact_level: str | None = Field(None, description="Impact level (if defined).")
    question_type: str | None = Field(None, description="Type (e.g., single-choice).")
    domain: str | None = Field(None, description="Domain/category.")
    source: str | None = Field(None, description="Where it came from.")
    status: str | None = Field(None, description="Active/Hidden/etc.")
    stem: str | None = Field(None, description="Question text.")
    answers: dict[str, Any] | None = Field(
        None, description="Options map for the replacement."
    )

    # UI flags
    isReplacement: bool = Field(
        default=True, description="(UI) Marks as replacement for the client."
    )
    reporting_disabled: bool = Field(
        default=True, description="(UI) Disables re-reporting in the client."
    )


class ReportAndReplaceResponse(BaseModel):
    reported_question_id: str = Field(
        ...,
        description="The original question you reported.",
        examples=["68af58d262d8b92758701355"],
    )
    report_id: str | None = Field(
        None, description="The stored report ID (if created).", examples=["6660cafe..."]
    )
    replacement_found: bool = Field(..., description="Whether we found a replacement.")
    relaxed_dimensions: list[str] = Field(
        default_factory=list,
        description="Match criteria we had to relax (if any).",
        examples=[["topic", "impact_level"]],
    )
    message: str | None = Field(
        None, description="Description of the issue by the user who raised the dispute."
    )
    replacement: ReplacementQuestionOut | None = Field(
        None, description="Replacement question (when available)."
    )
