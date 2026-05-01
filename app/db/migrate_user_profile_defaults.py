"""
One-time migration: fill missing user department/designation defaults.

Run:
    python -m app.db.migrate_user_profile_defaults
"""

from app.db.session import init_db, close_db
from app.models.user import User


DEFAULT_DEPARTMENT = "Engineering"
DEFAULT_DESIGNATION = "Team Member"


async def run_migration() -> None:
    await init_db()
    try:
        users = await User.find(User.is_deleted == False).to_list()
        updated = 0
        for user in users:
            changed = False
            if not getattr(user, "department", None):
                user.department = DEFAULT_DEPARTMENT
                changed = True
            if not getattr(user, "designation", None):
                user.designation = DEFAULT_DESIGNATION
                changed = True
            if changed:
                await user.save()
                updated += 1
        print(f"Migration complete. Updated {updated} users.")
    finally:
        await close_db()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_migration())
