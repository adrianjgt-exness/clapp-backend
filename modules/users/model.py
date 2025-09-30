from datetime import datetime as dt

from pydantic import BaseModel, EmailStr, Field


class UserOrganizationalUnit(BaseModel):
    """
    Represents a simplified organizational unit (team, department, etc.)
    stored within the user's profile.
    """

    hris_org_unit_id: str
    name: str


class UserProfile(BaseModel):
    """
    Represents the detailed user profile stored in your database.
    """

    id: str = Field(..., alias="_id")
    email: EmailStr
    name: str
    job_title: str | None = None
    picture: str | None = None
    hris_employee_id: str | None = None
    employee_number: str | None = None
    team: UserOrganizationalUnit | None = None
    department: UserOrganizationalUnit | None = None
    division: UserOrganizationalUnit | None = None
    user_role: str | None
    is_admin: bool | None = False
    registered_at: dt | None = None
    last_login_at: dt | None = None

    class Config:
        populate_by_name = True
        json_encoders = {dt: lambda v: v.isoformat()}


class UserUpdateRequest(BaseModel):
    """
    Model for the payload to update a user's role and admin status.
    """

    user_id: str
    new_role: str
    is_admin: bool


class UserListItem(BaseModel):
    """
    A simplified user model for listing users for test invitations.
    Only includes the necessary fields.
    """

    id: str = Field(..., alias="_id")
    name: str
    user_role: str | None

    class Config:
        populate_by_name = True
