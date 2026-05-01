from typing import Optional, List
from pydantic import BaseModel, UUID4, EmailStr

class UserBase(BaseModel):
    employee_code: str
    full_name: str
    email: EmailStr
    status: Optional[str] = "Active"
    department: Optional[str] = None
    designation: Optional[str] = None
    role_id: Optional[UUID4] = None
    reporting_admin_id: Optional[UUID4] = None

class UserCreate(UserBase):
    password: str
    role_id: UUID4  # required when creating a user

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    status: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    role_id: Optional[UUID4] = None
    reporting_admin_id: Optional[UUID4] = None

class UserInDBBase(UserBase):
    id: UUID4
    
    model_config = {"from_attributes": True}

class User(UserInDBBase):
    pass

from .role import Role

class UserWithDetails(UserInDBBase):
    role: Optional[Role] = None
