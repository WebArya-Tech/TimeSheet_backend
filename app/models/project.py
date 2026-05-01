import uuid
from typing import Optional
from datetime import date
from beanie import Document, Indexed, Link
from pydantic import Field, UUID4

from app.models.user import User

class Project(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    project_code: Indexed(str, unique=True)
    name: str
    expected_completion_date: date
    status: str = "Active"
    billable_type: str
    is_deleted: bool = False

    class Settings:
        name = "projects"

class ProjectAssignment(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    project_id: UUID4
    user_id: UUID4

    class Settings:
        name = "project_assignments"
