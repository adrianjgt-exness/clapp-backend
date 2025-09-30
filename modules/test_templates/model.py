from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

# Pydantic's Field class allows us to define an alias for the '_id' field from MongoDB,
# so we can use the more Python-friendly 'id' in our code.
PyObjectId = Annotated[str, BeforeValidator(str)]


class TestTemplateBase(BaseModel):
    """
    Base model containing all the core fields of a test template.
    This structure is shared for creation, updates, and responses.
    """

    template_name: str = Field(...)
    total_questions: int = Field(...)
    test_duration: int = Field(...)
    question_types: dict[str, int] = Field(...)
    selected_topic: list[str] = Field(...)
    domains: dict[str, int] = Field(...)
    sources: dict[str, int] = Field(...)
    selected_author: str = Field(...)
    impact_levels: dict[str, int] = Field(...)

    class Config:
        from_attributes = True
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class TestTemplateCreate(TestTemplateBase):
    """
    Model used when creating a new test template.
    It requires the 'created_by' field.
    """

    created_by: str = Field(...)


class TestTemplateUpdate(BaseModel):
    """
    Model for updating a template. All fields are optional to allow for partial updates.
    """

    template_name: str | None = Field(None)
    total_questions: int | None = Field(None)
    test_duration: int | None = Field(None)
    question_types: dict[str, int] | None = Field(None)
    selected_topic: list[str] | None = Field(None)
    domains: dict[str, int] | None = Field(None)
    sources: dict[str, int] | None = Field(None)
    selected_author: str | None = Field(None)
    impact_levels: dict[str, int] | None = Field(None)


class TestTemplateInDB(TestTemplateBase):
    """
    Represents the full Test Template document as stored in MongoDB.
    Includes backend-managed fields like timestamps and the 'is_common' flag.
    """

    id: PyObjectId = Field(alias="_id")
    created_by: str = Field(...)
    is_common: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    last_modified: datetime = Field(default_factory=datetime.now)


# ---------- Preview (strict checker) DTOs ----------


class QuotaCell(BaseModel):
    requested: int = 0
    available: int = 0
    selected: int = 0
    shortfall: int = 0


class QuotaMatrix(BaseModel):
    # Use default_factory to avoid shared mutable defaults
    question_types: dict[str, QuotaCell] = Field(default_factory=dict)
    domains: dict[str, QuotaCell] = Field(default_factory=dict)
    sources: dict[str, QuotaCell] = Field(default_factory=dict)
    impact_levels: dict[str, QuotaCell] = Field(default_factory=dict)


class TemplatePreviewRequest(BaseModel):
    """
    Request body for the strict (no-relaxation) template feasibility checker.
    Date-window and reuse are intentionally excluded per requirements.
    """

    template_name: str | None = None
    total_questions: int
    test_duration: int | None = 0
    # Safe defaults via default_factory
    question_types: dict[str, int] = Field(default_factory=dict)
    selected_topic: list[str] = Field(default_factory=list)
    domains: dict[str, int] = Field(default_factory=dict)
    sources: dict[str, int] = Field(default_factory=dict)
    selected_author: str | None = "All"
    impact_levels: dict[str, int] = Field(default_factory=dict)


# ---- Suggested FIX PLAN (actionable & verified) ----


class PlanDelta(BaseModel):
    # Per-category +/- deltas (counts) to apply to quotas
    domains: dict[str, int] = Field(default_factory=dict)
    question_types: dict[str, int] = Field(default_factory=dict)
    sources: dict[str, int] = Field(default_factory=dict)
    impact_levels: dict[str, int] = Field(default_factory=dict)


class Unlocker(BaseModel):
    name: str | None = None
    will_resolve: bool | None = None
    selected_total_after: int | None = None


class Unlockers(BaseModel):
    author_all: Unlocker | None = None
    topics_all: Unlocker | None = None
    drop_dimension: dict[str, Unlocker] = Field(default_factory=dict)


class FallbackPlan(BaseModel):
    type: str = "mirror_selected"
    guaranteed: bool = True
    new_total: int = 0
    new_quotas: PlanDelta = Field(default_factory=PlanDelta)


class SuggestedPlan(BaseModel):
    # A single, aggregated plan that is verified to make the template feasible
    will_resolve: bool = False
    steps: int = 0
    increments: PlanDelta = Field(default_factory=PlanDelta)
    decrements: PlanDelta = Field(default_factory=PlanDelta)
    human_summary: str | None = None
    quotas_after: QuotaMatrix | None = None
    feasible_after: bool | None = None
    selected_total_after: int | None = None
    missing_total_after: int | None = None


class TemplatePreviewResponse(BaseModel):
    """
    Response for the strict feasibility preview.
    """

    feasible: bool
    total_needed: int
    selected_total: int
    missing_total: int
    quotas: QuotaMatrix
    diagnostics: dict[str, Any]
    suggested_plan: SuggestedPlan | None = None
    fallback_plan: FallbackPlan | None = None
    unlockers: Unlockers | None = None
