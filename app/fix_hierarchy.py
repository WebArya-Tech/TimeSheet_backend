import asyncio
from app.db.session import init_db, close_db
from app.models.user import User
from app.models.role import Role

async def fix():
    print("Connecting to database...")
    await init_db()
    
    # 1. Admin user ko dhoondhein
    admin = await User.find_one(User.email == "admin@company.com")
    if not admin:
        print("Error: Admin 'admin@company.com' nahi mila.")
        await close_db()
        return

    # 2. USER role ko dhoondhein
    user_role = await Role.find_one(Role.role_name == "USER")
    
    # 3. Saare regular users ko is admin se link karein
    users = await User.find(User.role.id == user_role.id).to_list()
    count = 0
    for u in users:
        if u.id != admin.id:
            u.reporting_admin_id = admin.id
            await u.save()
            print(f"Linked: {u.full_name} -> Manager: {admin.full_name}")
            count += 1
    
    print(f"\nSuccess! Total {count} users admin ke under assign ho gaye hain.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(fix())