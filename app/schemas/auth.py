from typing import Optional
from pydantic import BaseModel, EmailStr

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: Optional[str] = None

class Login(BaseModel):
    email: str
    password: str

class ForgotPassword(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    token: str
    new_password: str


class SignupRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    employee_code: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
