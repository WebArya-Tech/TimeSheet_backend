import uuid
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field, UUID4

class Role(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    role_name: Indexed(str, unique=True)
    status: str = "Active"
    is_deleted: bool = False

    class Settings:
        name = "roles"
