from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID

from app.api import deps
from app.models.user import User
from app.models.role import Role
from app.schemas.user import User as UserSchema, UserCreate, UserUpdate, UserWithDetails
from app.core.security import get_password_hash

router = APIRouter()

@router.get("/me", response_model=UserWithDetails)
async def read_current_user(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    # Manually instantiate to bypass Beanie/Pydantic validation conflicts
    return UserWithDetails(
        id=current_user.id,
        employee_code=current_user.employee_code,
        full_name=current_user.full_name,
        email=current_user.email,
        status=current_user.status,
        department=current_user.department,
        designation=current_user.designation,
        role_id=current_user.role.id if current_user.role else None,
        reporting_admin_id=current_user.reporting_admin_id,
        role=current_user.role
    )

@router.get("/", response_model=List[UserWithDetails])
async def read_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    users = await User.find(User.is_deleted == False, fetch_links=True).skip(skip).limit(limit).to_list(length=limit)
    return [
        UserWithDetails(
            id=u.id,
            employee_code=u.employee_code,
            full_name=u.full_name,
            email=u.email,
            status=u.status,
            department=u.department,
            designation=u.designation,
            role_id=u.role.id if u.role else None,
            reporting_admin_id=u.reporting_admin_id,
            role=u.role,
        )
        for u in users
    ]


@router.get("/meta")
async def get_users_meta(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    roles = await Role.find(Role.is_deleted == False).to_list()
    admins = await User.find(User.is_deleted == False, fetch_links=True).to_list()

    role_items = [{"id": str(r.id), "role_name": r.role_name, "status": r.status} for r in roles]
    admin_items = [
        {"id": str(u.id), "full_name": u.full_name, "employee_code": u.employee_code}
        for u in admins
        if u.role and u.role.role_name in ["ADMIN", "SUPER_ADMIN"]
    ]

    return {"roles": role_items, "admins": admin_items}

@router.post("/", response_model=UserSchema)
async def create_user(
    *,
    user_in: UserCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    user = await User.find_one(User.email == user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    role = await Role.find_one(Role.id == user_in.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if current_user.role.role_name == "ADMIN" and role.role_name in {"ADMIN", "SUPER_ADMIN"}:
        raise HTTPException(status_code=403, detail="Admins may only create regular users")
        
    db_user = User(
        employee_code=user_in.employee_code,
        full_name=user_in.full_name,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
        status=user_in.status,
        department=user_in.department,
        designation=user_in.designation,
        role=role,
        reporting_admin_id=user_in.reporting_admin_id
    )
    await db_user.insert()
    return db_user

@router.put("/{id}", response_model=UserSchema)
async def update_user(
    *,
    id: UUID,
    user_in: UserUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    user = await User.find_one(User.id == id, User.is_deleted == False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_in.model_dump(exclude_unset=True)
    if "role_id" in update_data:
        role = await Role.find_one(Role.id == update_data["role_id"])
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if current_user.role.role_name == "ADMIN" and role.role_name in {"ADMIN", "SUPER_ADMIN"}:
            raise HTTPException(status_code=403, detail="Admins may only assign regular user roles")
        user.role = role
        del update_data["role_id"]
        
    for field, value in update_data.items():
        setattr(user, field, value)
        
    await user.save()
    return user

@router.put("/{id}/status", response_model=UserSchema)
async def update_user_status(
    *,
    id: UUID,
    status: str,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    user = await User.find_one(User.id == id, User.is_deleted == False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.status = status
    await user.save()
    return user
