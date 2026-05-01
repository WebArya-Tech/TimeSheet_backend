import uuid
from typing import Optional
from datetime import datetime
from beanie import Document, Link
from pydantic import Field, UUID4
from app.models.user import User

class Notification(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    user: Link[User]
    type: str # "reminder" | "warning" | "success" | "info" | "error"
    title: str
    message: str
    link: Optional[str] = None
    is_read: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "notifications"
