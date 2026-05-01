import uuid
from typing import Optional
from beanie import Document, Link
from pydantic import Field, UUID4
from app.models.user import User

class Attendance(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    user: Link[User]
    date: str # YYYY-MM-DD
    status: str # "present" | "absent" | "leave" | "holiday" | "half-day" | "weekend" | "wfh" | "late"
    check_in: Optional[str] = None # HH:MM
    check_out: Optional[str] = None # HH:MM
    hours: Optional[float] = None
    note: Optional[str] = None
    approval_status: str = "pending" # "pending" | "approved" | "rejected"
    approved_by: Optional[Link[User]] = None
    approver_comment: Optional[str] = None

    class Settings:
        name = "attendances"
