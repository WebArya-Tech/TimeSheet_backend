from app.models.notification import Notification
from app.models.user import User
from app.models.role import Role

async def create_global_notification(
    type: str,
    title: str,
    message: str,
    link: str = None,
    target_user: User = None,
    actor: User = None
):
    """
    Creates a notification for the target user AND a read-only copy for all SUPER_ADMINs.
    """
    if target_user:
        await Notification(user=target_user, type=type, title=title, message=message, link=link).insert()

    super_admin_role = await Role.find_one(Role.role_name == "SUPER_ADMIN")
    if super_admin_role:
        super_admins = await User.find(User.role.id == super_admin_role.id, User.is_deleted == False).to_list()
        actor_name = actor.full_name if actor else "System"
        for sa in super_admins:
            if target_user and sa.id == target_user.id: continue
            await Notification(user=sa, type=type, title=f"[Global] {title}", message=f"Activity by {actor_name} on {target_user.full_name if target_user else 'user'}: {message}", link=link).insert()