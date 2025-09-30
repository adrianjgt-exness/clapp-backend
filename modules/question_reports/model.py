from datetime import datetime

from pydantic import BaseModel, Field


class QuestionReportCreate(BaseModel):
    """
    Data stored when a user reports a question.
    """

    question_id: str = Field(
        ...,
        description="ID of the question being reported.",
        examples=["68af58d262d8b92758701355"],
    )
    user_id: str = Field(
        ...,
        description="ID of the user who submitted the report.",
        examples=["6866110adc35eb417a0462b4"],
    )
    test_id: str = Field(
        ...,
        description="ID of the test where the issue happened.",
        examples=["68a93019feccc12ae5074868"],
    )
    comment: str = Field(
        ...,
        description="Brief explanation of the problem.",
        examples=["Option C should be different to be correct."],
    )


class QuestionReportInDB(QuestionReportCreate):
    """
    Model representing the full report document as stored in the database.
    """

    id: str | None = Field(
        None,
        alias="_id",
        description="Internal database identifier.",
        examples=["665f2c9b1a2b3c4d5e6f7a8b"],
    )
    reported_at: datetime = Field(
        default_factory=datetime.now,
        description="When the report was created (server time).",
        examples=["2025-08-27T12:00:00Z"],
    )
    status: str = Field(
        default="open",
        description='Workflow status (e.g., "open", "resolved", "dismissed").',
        examples=["open"],
    )

    class Config:
        from_attributes = True
        populate_by_name = True


class ReportRequest(BaseModel):
    user_id: str = Field(
        ...,
        description="ID of the signed-in user.",
        examples=["6866110adc35eb417a0462b4"],
    )
    test_id: str = Field(
        ...,
        description="The test where the reported question appears.",
        examples=["68a93019feccc12ae5074868"],
    )
    comment: str = Field(
        ...,
        description="Short note describing what is wrong.",
        examples=["Image is missing; question cannot be answered."],
    )
