from typing import Optional, List
from datetime import date
from pydantic import BaseModel, UUID4

class TimesheetEntryBase(BaseModel):
    date: date
    entry_type: str
    project_id: Optional[UUID4] = None
    category_id: Optional[UUID4] = None
    task: Optional[str] = None
    sub_task: Optional[str] = None
    hours: float
    remarks: Optional[str] = None

class TimesheetEntryCreate(TimesheetEntryBase):
    pass

class TimesheetEntryUpdate(BaseModel):
    entry_type: Optional[str] = None
    project_id: Optional[UUID4] = None
    category_id: Optional[UUID4] = None
    task: Optional[str] = None
    sub_task: Optional[str] = None
    hours: Optional[float] = None
    remarks: Optional[str] = None

class TimesheetEntry(TimesheetEntryBase):
    id: UUID4
    timesheet_id: UUID4

    model_config = {"from_attributes": True}

class TimesheetHeaderBase(BaseModel):
    user_id: UUID4
    week_start: date
    week_end: date
    total_hours: float = 0.0
    status: str = "Draft"
    admin_comment: Optional[str] = None

class TimesheetHeaderCreate(BaseModel):
    week_start: date
    week_end: date

class TimesheetHeaderUpdate(BaseModel):
    status: Optional[str] = None
    admin_comment: Optional[str] = None

class TimesheetHeader(TimesheetHeaderBase):
    id: UUID4
    entries: List[TimesheetEntry] = []

    model_config = {"from_attributes": True}

class TimesheetApproval(BaseModel):
    status: str # Approved, Returned
    admin_comment: Optional[str] = None
