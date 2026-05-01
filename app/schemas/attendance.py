from typing import Optional, List
from pydantic import BaseModel, UUID4
from app.schemas.user import UserWithDetails

class AttendanceBase(BaseModel):
    date: str
    status: str
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    hours: Optional[float] = None
    note: Optional[str] = None

class AttendanceCreate(AttendanceBase):
    pass

class AttendanceUpdate(AttendanceBase):
    pass

class AttendanceApprovalUpdate(BaseModel):
    approval_status: str
    approver_comment: Optional[str] = None

class AttendanceInDBBase(AttendanceBase):
    id: UUID4
    user_id: UUID4
    approval_status: str
    approved_by_id: Optional[UUID4] = None
    approver_comment: Optional[str] = None

    model_config = {"from_attributes": True}

class AttendanceWithDetails(AttendanceInDBBase):
    user: Optional[UserWithDetails] = None
    approved_by: Optional[UserWithDetails] = None


class AttendanceMarkRequest(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
