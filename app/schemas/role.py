from typing import Optional
from pydantic import BaseModel, UUID4, EmailStr

class RoleBase(BaseModel):
    role_name: str
    status: Optional[str] = "Active"

class RoleCreate(RoleBase):
    pass

class RoleUpdate(RoleBase):
    role_name: Optional[str] = None
    status: Optional[str] = None

class RoleInDBBase(RoleBase):
    id: UUID4

    model_config = {"from_attributes": True}

class Role(RoleInDBBase):
    pass
