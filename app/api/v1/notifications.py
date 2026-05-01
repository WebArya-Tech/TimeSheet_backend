from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID

from app.api import deps
from app.models.user import User
from app.models.notification import Notification
from app.schemas.notification import NotificationCreate

router = APIRouter()


def _serialize_notification(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "link": getattr(n, "link", None),
        "is_read": n.is_read,
        "created_at": n.created_at,
    }


@router.get("/", response_model=List[Any])
async def read_my_notifications(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    records = await Notification.find({"user.$id": current_user.id}).sort(-Notification.created_at).to_list()
    return [_serialize_notification(n) for n in records]


@router.post("/", response_model=Any)
async def create_notification(
    *,
    payload: NotificationCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    user = await User.find_one(User.id == payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    n = Notification(
        user=user,
        type=payload.type,
        title=payload.title,
        message=payload.message,
        link=getattr(payload, "link", None),
        is_read=False,
    )
    await n.insert()
    return _serialize_notification(n)


@router.put("/{id}/read", response_model=Any)
async def mark_notification_read(
    *,
    id: UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    n = await Notification.find_one(Notification.id == id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    if getattr(n.user, "id", None) != current_user.id:
        # handle both Link and already-fetched User
        linked_user = None
        user_field = getattr(n, "user", None)
        if user_field is None:
            linked_user = None
        elif hasattr(user_field, "fetch") and callable(user_field.fetch):
            linked_user = await user_field.fetch()
        else:
            linked_user = user_field

        if not linked_user or getattr(linked_user, "id", None) != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough privileges")
    n.is_read = True
    await n.save()
    return {"msg": "Notification marked as read"}


@router.put("/read-all", response_model=Any)
async def mark_all_notifications_read(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    records = await Notification.find({"user.$id": current_user.id, "is_read": False}).to_list()
    for n in records:
        n.is_read = True
        await n.save()
    return {"msg": "All notifications marked as read"}
