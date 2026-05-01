from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from uuid import UUID

from app.core.config import settings
from app.models.user import User
from app.schemas.auth import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"]
        )
        token_data = TokenPayload(**payload)
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
        
    try:
        user_uuid = UUID(token_data.sub)
    except:
        raise HTTPException(status_code=400, detail="Invalid token subject")

    user = await User.find_one(User.id == user_uuid, fetch_links=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.status != "Active":
        raise HTTPException(status_code=400, detail="Inactive user")
    return user

async def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role.role_name != "SUPER_ADMIN":
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user

async def get_current_active_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role.role_name not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user


async def get_current_admin_only(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require role ADMIN or SUPER_ADMIN for management actions."""
    if current_user.role.role_name not in ["ADMIN", "SUPER_ADMIN"]:
        raise HTTPException(
            status_code=400, detail="The user doesn't have enough privileges"
        )
    return current_user
