from typing import Optional, List
from pydantic import BaseModel, UUID4
from app.schemas.user import UserWithDetails

class LeaveBase(BaseModel):
    leave_type: str
    from_date: str
    to_date: str
    days: int
    reason: str

class LeaveCreate(LeaveBase):
    pass

class LeaveUpdate(BaseModel):
    status: str
    approver_comment: Optional[str] = None

class LeaveInDBBase(LeaveBase):
    id: UUID4
    user_id: UUID4
    status: str
    applied_on: str
    approved_by_id: Optional[UUID4] = None
    approver_comment: Optional[str] = None
    
    model_config = {"from_attributes": True}

class LeaveWithDetails(LeaveInDBBase):
    user: Optional[UserWithDetails] = None
    approved_by: Optional[UserWithDetails] = None
