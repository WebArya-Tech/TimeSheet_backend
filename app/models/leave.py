import uuid
from typing import Optional
from beanie import Document, Link
from pydantic import Field, UUID4
from app.models.user import User

class Leave(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    user: Link[User]
    leave_type: str  # "casual", "sick", "earned", "compoff", "maternity", "paternity", "unpaid"
    from_date: str # YYYY-MM-DD
    to_date: str # YYYY-MM-DD
    days: int
    reason: str
    status: str = "pending"  # "pending", "approved", "rejected", "cancelled"
    applied_on: str # YYYY-MM-DD
    approved_by: Optional[Link[User]] = None
    approver_comment: Optional[str] = None
    
    class Settings:
        name = "leaves"
