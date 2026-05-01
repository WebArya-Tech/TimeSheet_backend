from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from datetime import datetime

from app.api import deps
from app.models.user import User
from app.models.leave import Leave
from app.models.notification import Notification
from app.models.role import Role
from app.models.audit_log import AuditLog
from beanie.operators import In
from app.schemas.leave import LeaveCreate, LeaveUpdate, LeaveWithDetails
import traceback
import logging
from app.api.v1.system import create_global_notification

router = APIRouter()

@router.get("/my", response_model=List[Any])
async def read_my_leaves(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    leaves = await Leave.find(Leave.user.id == current_user.id, fetch_links=True).to_list()
    results = []
    for l in leaves:
        ld = l.model_dump()
        ld["user_id"] = current_user.id
        ld["approved_by_id"] = l.approved_by.id if getattr(l, "approved_by", None) else None
        
        # Format for UI compatibility
        ld["from"] = ld["from_date"]
        ld["to"] = ld["to_date"]
        ld["type"] = ld["leave_type"]
        results.append(ld)
    return results

@router.post("/", response_model=Any)
async def create_leave(
    *,
    leave_in: LeaveCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    db_leave = Leave(
        user=current_user,
        leave_type=leave_in.leave_type,
        from_date=leave_in.from_date,
        to_date=leave_in.to_date,
        days=leave_in.days,
        reason=leave_in.reason,
        applied_on=datetime.utcnow().strftime("%Y-%m-%d"),
        status="pending"
    )
    await db_leave.insert()
    
    admin_user = None
    if current_user.reporting_admin_id:
        admin_user = await User.find_one(User.id == current_user.reporting_admin_id)
        
    await create_global_notification(
        type="info",
        title="Leave Applied",
        message=f"{current_user.full_name} applied for leave from {leave_in.from_date} to {leave_in.to_date}.",
        link="/leave-approvals",
        target_user=admin_user,
        actor=current_user
    )
    
    ld = db_leave.model_dump()
    ld["from"] = ld["from_date"]
    ld["to"] = ld["to_date"]
    ld["type"] = ld["leave_type"]
    return ld

@router.put("/{id}/cancel", response_model=Any)
async def cancel_leave(
    *,
    id: UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    leave = await Leave.find_one(Leave.id == id, fetch_links=True)
    if not leave:
        raise HTTPException(status_code=404, detail="Leave not found")
    if leave.user.id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this leave")
    if leave.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending leaves can be cancelled")
        
    leave.status = "cancelled"
    await leave.save()
    
    ld = leave.model_dump()
    ld["from"] = ld["from_date"]
    ld["to"] = ld["to_date"]
    ld["type"] = ld["leave_type"]
    return ld

@router.put("/{id}/status", response_model=Any)
async def update_leave_status(
    *,
    id: UUID,
    leave_in: LeaveUpdate,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    try:
        leave = await Leave.find_one(Leave.id == id, fetch_links=True)
        if not leave:
            raise HTTPException(status_code=404, detail="Leave not found")

        prev_status = leave.status

        if current_user.role.role_name == "ADMIN":
            target_user = leave.user
            if hasattr(target_user, "fetch") and callable(target_user.fetch):
                target_user = await target_user.fetch()
            
            if target_user and hasattr(target_user, "role"):
                target_role = target_user.role.role_name if hasattr(target_user.role, "role_name") else ""
                if target_role != "USER":
                    raise HTTPException(status_code=403, detail="Admin may only approve regular user leaves")
        elif current_user.role.role_name == "SUPER_ADMIN":
            target_user = leave.user
            if hasattr(target_user, "fetch") and callable(target_user.fetch):
                target_user = await target_user.fetch()
            if target_user and hasattr(target_user, "role"):
                target_role = target_user.role.role_name if hasattr(target_user.role, "role_name") else ""
                if target_role == "USER":
                    raise HTTPException(status_code=403, detail="Super Admin has read-only visibility for regular users")

        leave.status = leave_in.status
        leave.approver_comment = leave_in.approver_comment or ("Approved by admin" if leave_in.status == "approved" else "Rejected by admin")
        leave.approved_by = current_user
        await leave.save()

        target_uid = None
        if getattr(leave, "user", None) is not None and hasattr(leave.user, "id"):
            target_uid = leave.user.id

        await AuditLog(
            user_id=current_user.id,
            target_user_id=target_uid,
            action=leave_in.status.capitalize(),
            module="LeaveApprovals",
            old_value=f"status={prev_status}",
            new_value=f"status={leave.status}; approver_comment={leave.approver_comment}",
        ).insert()

        # Add notification for user — handle both Link and already-fetched User
        try:
            target_user = None
            if getattr(leave, "user", None) is not None:
                user_field = leave.user
                if hasattr(user_field, "fetch") and callable(user_field.fetch):
                    target_user = await user_field.fetch()
                else:
                    target_user = user_field
            if target_user:
                await create_global_notification(
                    type="info" if leave_in.status == "approved" else "warning",
                    title=f"Leave {leave_in.status.capitalize()} by Admin",
                    message=f"Your leave request from {leave.from_date} to {leave.to_date} has been {leave_in.status}.",
                    link=f"/leave-approvals?record={leave.id}",
                    target_user=target_user,
                    actor=current_user
                )
        except Exception:
            logging.exception("Failed to notify leave requester")

        ld = leave.model_dump()
        ld["from"] = ld["from_date"]
        ld["to"] = ld["to_date"]
        ld["type"] = ld["leave_type"]
        return ld
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error updating leave status")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending", response_model=List[Any])
async def read_pending_leaves(
    current_user: User = Depends(deps.get_current_active_admin),
    status: str = "pending",
) -> Any:
    if status not in {"pending", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid leave status")

    if current_user.role.role_name == "SUPER_ADMIN":
        leaves = await Leave.find(Leave.status == status, fetch_links=True).to_list()
    else:
        reporting_users = await User.find(User.reporting_admin_id == current_user.id, User.is_deleted == False).to_list()
        reporting_user_ids = [u.id for u in reporting_users]
        if not reporting_user_ids:
            return []
        leaves = await Leave.find(Leave.status == status, In(Leave.user.id, reporting_user_ids), fetch_links=True).to_list()

    results = []
    for l in leaves:
        ld = l.model_dump()
        ld["user_id"] = l.user.id if getattr(l, "user", None) else None
        ld["approved_by_id"] = l.approved_by.id if getattr(l, "approved_by", None) else None
        ld["from"] = ld["from_date"]
        ld["to"] = ld["to_date"]
        ld["type"] = ld["leave_type"]
        if getattr(l, "user", None):
            user_data = l.user.model_dump()
            user_data.pop("hashed_password", None)
            ld["user"] = user_data
        if getattr(l, "approved_by", None):
            ld["approved_by"] = l.approved_by.model_dump()
        results.append(ld)
    return results

@router.get("/all", response_model=List[Any])
async def read_all_leaves(
    current_user: User = Depends(deps.get_current_active_admin),
    status: str | None = None,
) -> Any:
    query = Leave.find(fetch_links=True)
    if status:
        if status not in {"pending", "approved", "rejected", "cancelled"}:
            raise HTTPException(status_code=400, detail="Invalid leave status")
        query = query.filter(Leave.status == status)

    leaves = await query.to_list()
    results = []
    for l in leaves:
        ld = l.model_dump()
        ld["user_id"] = l.user.id if getattr(l, "user", None) else None
        ld["approved_by_id"] = l.approved_by.id if getattr(l, "approved_by", None) else None
        ld["from"] = ld["from_date"]
        ld["to"] = ld["to_date"]
        ld["type"] = ld["leave_type"]
        if getattr(l, "user", None):
            ld["user"] = l.user.model_dump()
        results.append(ld)
    return results
