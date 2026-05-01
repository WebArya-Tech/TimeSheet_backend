import uuid
from typing import Optional
from datetime import datetime
from beanie import Document
from pydantic import Field, UUID4

class AuditLog(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    user_id: UUID4
    action: str
    module: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    # The target record's owner (e.g., employee whose leave/attendance/timesheet was approved).
    # Optional to keep backward compatibility with existing audit log documents.
    target_user_id: Optional[UUID4] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "audit_logs"
