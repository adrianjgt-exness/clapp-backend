from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class OrganizationalUnit(BaseModel):
    """
    A model for organizational units like team, department, etc.
    """

    hris_org_unit_id: str = Field(
        ..., description="Internal identifier for this org unit.", examples=["TEAM-45"]
    )
    name: str = Field(
        ...,
        description="Human-readable name of the org unit.",
        examples=["Training Ops"],
    )
    is_archived: bool = Field(
        ...,
        description="Whether this org unit is archived (no longer active).",
        examples=[False],
    )
    level: int = Field(
        ...,
        description="Hierarchy level (0=Company, 1=Division, 2=Department, 3=Team).",
        examples=[3],
    )


class HibobEmployee(BaseModel):
    """
    Represents the detailed employee data returned from the HiBob API,
    tailored to the actual fields received.
    """

    hris_employee_id: str = Field(
        ...,
        description="Internal employee identifier.",
        examples=["3263412116404568102"],
    )
    employee_number: str = Field(
        ..., description="Public/HR employee code.", examples=["3211"]
    )
    first_name: str = Field(..., description="Given name.", examples=["Ana"])
    last_name: str = Field(..., description="Family name.", examples=["Pereira"])
    middle_name: str | None = Field(
        None, description="Middle name (if any).", examples=[None]
    )
    display_name: str = Field(
        ...,
        description="How the name should appear in the app.",
        examples=["Ana Pereira"],
    )
    job_title: str = Field(
        ..., description="Current role/title.", examples=["Training Specialist"]
    )
    email: EmailStr = Field(
        ..., description="Corporate email address.", examples=["ana.pereira@exness.com"]
    )
    photo: str = Field(
        ...,
        description="URL to the profile photo.",
        examples=["https://hibob.example/photos/emp_001234.jpg"],
    )
    team: OrganizationalUnit | None = Field(
        None, description="Employee’s team (if defined)."
    )
    department: OrganizationalUnit | None = Field(
        None, description="Employee’s department (if defined)."
    )
    division: OrganizationalUnit = Field(..., description="Employee’s division.")
    company: OrganizationalUnit = Field(..., description="Top-level company org unit.")
    created_at: datetime = Field(
        ...,
        description="When this record was created (UTC).",
        examples=["2025-07-21T14:36:00Z"],
    )
    checksum: str = Field(
        ...,
        description="Integrity hash for the record.",
        examples=["e288ee43062e4ca83307877dd8e3ed83"],
    )

    class Config:
        from_attributes = True
