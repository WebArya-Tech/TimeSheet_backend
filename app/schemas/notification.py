from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, UUID4

class NotificationBase(BaseModel):
    type: str
    title: str
    message: str
    link: Optional[str] = None

class NotificationCreate(NotificationBase):
    user_id: UUID4

class NotificationInDBBase(NotificationBase):
    id: UUID4
    is_read: bool
    created_at: datetime
    
    model_config = {"from_attributes": True}

class Notification(NotificationInDBBase):
    pass
