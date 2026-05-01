import logging

from app.core.config import settings
from app.models.role import Role
from app.models.user import User
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)

async def init_seed_data() -> None:
    logger.info("Checking seed data...")
    roles = ["SUPER_ADMIN", "ADMIN", "USER"]
    role_map = {}
    
    for r in roles:
        role = await Role.find_one(Role.role_name == r)
        if not role:
            role = Role(role_name=r)
            await role.insert()
        role_map[r] = role

    user = await User.find_one(User.email == settings.FIRST_SUPERUSER)
    if not user:
        user = User(
            employee_code="SA-001",
            full_name="Super Administrator",
            email=settings.FIRST_SUPERUSER,
            password_hash=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
            role=role_map["SUPER_ADMIN"],
        )
        await user.insert()
        logger.info("Super admin created successfully.")
    else:
        logger.info("Super admin already exists.")

    admin = await User.find_one(User.email == "admin@company.com")
    if not admin:
        admin = User(
            employee_code="AD-001",
            full_name="Admin User",
            email="admin@company.com",
            password_hash=get_password_hash("demo"),
            role=role_map["ADMIN"],
        )
        await admin.insert()
        logger.info("Admin created successfully.")

    standard_user = await User.find_one(User.email == "user@company.com")
    if not standard_user:
        standard_user = User(
            employee_code="US-001",
            full_name="Standard User",
            email="user@company.com",
            password_hash=get_password_hash("demo"),
            role=role_map["USER"],
        )
        await standard_user.insert()
        logger.info("Standard user created successfully.")

if __name__ == "__main__":
    import asyncio
    from app.db.session import init_db, close_db
    async def main():
        await init_db()
        await init_seed_data()
        await close_db()
    asyncio.run(main())
