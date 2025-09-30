from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

PyObjectId = Annotated[str, BeforeValidator(str)]


class TestBase(BaseModel):
    """
    Base model containing all common fields for a Test.
    The other models will inherit from this to avoid repetition.
    """

    test_name: str = Field(...)
    open_date: date = Field(...)
    close_date: date = Field(...)
    questions_from_date: date = Field(...)
    questions_to_date: date = Field(...)

    class Config:
        # Allows the model to be created from a dictionary or an ORM object.
        from_attributes = True
        # Defines how JSON serialization should be handled, especially for datetime objects.
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
        }


class TestCreate(TestBase):
    """
    Model for creating a new test. Inherits fields from TestBase
    and adds the 'created_by' field, which is required on creation.
    """

    created_by: str = Field(...)


class TestUpdate(BaseModel):
    """
    Model for updating an existing test. All fields are optional
    so the frontend can send only the fields that have changed.
    """

    test_name: str | None = None
    open_date: date | None = None
    close_date: date | None = None
    questions_from_date: date | None = None
    questions_to_date: date | None = None


class TestInDB(TestBase):
    """
    Model representing the full Test document as it is stored in the database.
    It includes fields that are managed by the backend, like status and timestamps.
    """

    id: PyObjectId = Field(alias="_id")
    created_by: str = Field(...)
    status: str = "draft"
    invited_users: list[str] = []
    template_details: dict | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    last_updated_at: datetime = Field(default_factory=datetime.now)


# --- Request Models for Specific Actions ---


class TestInvitationRequest(BaseModel):
    """
    Model for the request to save invited users. This matches the
    structure sent from the frontend in step 2.
    """

    invited_users: list[str] = Field(..., description="A list of user IDs.")

    class Config:
        populate_by_name = True


class TestFinalizeRequest(BaseModel):
    """
    Model for the request to finalize a test. This matches the
    data sent from the frontend in the final step.
    """

    template_type: str = Field(..., description="Either 'common' or 'private'.")
    template_name: str = Field(...)
    template_id: str | None = None

    class Config:
        populate_by_name = True
