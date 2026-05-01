import uuid
from typing import Optional, List
from datetime import date
from beanie import Document, Indexed
from pydantic import Field, UUID4

class TimesheetEntry(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    timesheet_id: UUID4
    date: date
    entry_type: str
    project_id: Optional[UUID4] = None
    category_id: Optional[UUID4] = None
    task: Optional[str] = None
    sub_task: Optional[str] = None
    hours: float
    remarks: Optional[str] = None
    is_deleted: bool = False

    class Settings:
        name = "timesheet_entries"


class TimesheetHeader(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    user_id: UUID4
    week_start: date
    week_end: date
    total_hours: float = 0.0
    status: str = "Draft"
    admin_comment: Optional[str] = None

    class Settings:
        name = "timesheet_headers"
