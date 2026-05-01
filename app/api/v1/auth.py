from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from app.core import security
from app.core.config import settings
from app.models.user import User
from app.models.role import Role
from app.schemas.auth import Token, ForgotPassword, ResetPassword, SignupRequest
from app.core.security import get_password_hash

router = APIRouter()

@router.post("/login", response_model=Token)
async def login_access_token(
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    user = await User.find_one(User.email == form_data.username)
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif user.status != "Active":
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return {
        "access_token": security.create_access_token(
            user.id, expires_delta=access_token_expires
        ),
        "token_type": "bearer",
    }

@router.post("/logout")
async def logout() -> Any:
    return {"msg": "Successfully logged out"}

@router.post("/forgot-password")
async def forgot_password(data: ForgotPassword) -> Any:
    user = await User.find_one(User.email == data.email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist.",
        )
    reset_token = security.create_reset_password_token(user.email)
    # In production this token should be sent via email. Returned here for development/testing.
    return {"msg": "Password recovery email sent", "reset_token": reset_token}

@router.post("/reset-password")
async def reset_password(data: ResetPassword) -> Any:
    email = security.verify_reset_password_token(data.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = await User.find_one(User.email == email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.password_hash = get_password_hash(data.new_password)
    await user.save()
    return {"msg": "Password has been reset successfully"}


@router.post("/signup")
async def signup(data: SignupRequest) -> Any:
    existing = await User.find_one(User.email == data.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = await Role.find_one(Role.role_name == "USER")
    if not role:
        role = Role(role_name="USER")
        await role.insert()

    employee_code = data.employee_code or f"EMP-{str(data.email).split('@')[0].upper()[:8]}"

    existing_emp = await User.find_one(User.employee_code == employee_code)
    if existing_emp:
        employee_code = f"{employee_code}-{str(existing_emp.id)[:4]}"

    user = User(
        employee_code=employee_code,
        full_name=data.full_name,
        email=data.email,
        password_hash=get_password_hash(data.password),
        status="Active",
        role=role,
        department=data.department,
        designation=data.designation,
    )
    await user.insert()
    return {"msg": "Signup successful. Please login with your credentials."}
