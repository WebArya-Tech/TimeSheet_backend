from typing import Optional, List
from datetime import date
from pydantic import BaseModel, UUID4

class ProjectBase(BaseModel):
    project_code: str
    name: str
    expected_completion_date: date
    status: Optional[str] = "Active"
    billable_type: str

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    expected_completion_date: Optional[date] = None
    status: Optional[str] = None
    billable_type: Optional[str] = None

class ProjectInDBBase(ProjectBase):
    id: UUID4

    model_config = {"from_attributes": True}

class Project(ProjectInDBBase):
    pass

class ProjectAssignmentBase(BaseModel):
    project_id: UUID4
    user_id: UUID4

class ProjectAssignmentCreate(ProjectAssignmentBase):
    pass

class ProjectAssignment(ProjectAssignmentBase):
    id: UUID4

    model_config = {"from_attributes": True}


class ProjectAssignmentsUpdate(BaseModel):
    user_ids: List[UUID4]

class UserProjectAssignmentsUpdate(BaseModel):
    project_ids: List[UUID4]
