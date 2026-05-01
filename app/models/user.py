import uuid
from typing import Optional, List
from beanie import Document, Indexed, Link
from pydantic import Field, UUID4, EmailStr

from app.models.role import Role

class User(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    employee_code: Indexed(str, unique=True)
    full_name: str
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    status: str = "Active"
    department: Optional[str] = None
    designation: Optional[str] = None
    is_deleted: bool = False

    role: Link[Role]
    reporting_admin_id: Optional[UUID4] = None

    class Settings:
        name = "users"
