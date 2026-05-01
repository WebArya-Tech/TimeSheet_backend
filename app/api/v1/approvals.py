from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from beanie.operators import In

from app.api import deps
from app.models.timesheet import TimesheetHeader
from app.models.timesheet import TimesheetEntry
from app.models.project import Project
from app.models.category import Category
from app.models.user import User
from app.models.notification import Notification
from app.models.audit_log import AuditLog
from app.api.v1.system import create_global_notification
from app.schemas.timesheet import TimesheetApproval

router = APIRouter()


async def _serialize_entries(entries: list[TimesheetEntry]) -> list[dict[str, Any]]:
    if not entries:
        return []
    project_ids = list({e.project_id for e in entries if e.project_id})
    category_ids = list({e.category_id for e in entries if e.category_id})
    project_map: dict[Any, str] = {}
    category_map: dict[Any, str] = {}

    if project_ids:
        projects = await Project.find(In(Project.id, project_ids), Project.is_deleted == False).to_list()
        project_map = {p.id: p.name for p in projects}
    if category_ids:
        categories = await Category.find(In(Category.id, category_ids), Category.is_deleted == False).to_list()
        category_map = {c.id: c.category_name for c in categories}

    result: list[dict[str, Any]] = []
    for e in entries:
        d = e.model_dump()
        d["project_name"] = project_map.get(e.project_id)
        d["category_name"] = category_map.get(e.category_id)
        d["project_or_activity"] = d["project_name"] or d["category_name"] or d.get("task")
        result.append(d)
    return result

@router.get("/pending", response_model=List[Any])
async def get_pending_approvals(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    if current_user.role.role_name == "SUPER_ADMIN":
        headers = await TimesheetHeader.find(TimesheetHeader.status == "Submitted").to_list()
    else:
        # Need fetch_links=True to access u.role.role_name
        reporting_users = await User.find(User.reporting_admin_id == current_user.id, User.is_deleted == False, fetch_links=True).to_list()
        # Relaxed check: include any reporting user who isn't a SUPER_ADMIN
        reporting_user_ids = [u.id for u in reporting_users if u.role and u.role.role_name.upper() != "SUPER_ADMIN"]
        if not reporting_user_ids:
            return []
        headers = await TimesheetHeader.find(
            TimesheetHeader.status == "Submitted",
            In(TimesheetHeader.user_id, reporting_user_ids)
        ).to_list()
        
    if not headers:
        return []

    user_ids = [h.user_id for h in headers]
    users = await User.find(In(User.id, user_ids), fetch_links=True).to_list()
    user_map = {u.id: u for u in users}

    header_ids = [h.id for h in headers]
    entries = await TimesheetEntry.find(In(TimesheetEntry.timesheet_id, header_ids), TimesheetEntry.is_deleted == False).to_list()
    
    # Pre-fetch all projects and categories for all entries at once to avoid N+1 queries in the loop
    all_project_ids = list({e.project_id for e in entries if e.project_id})
    all_category_ids = list({e.category_id for e in entries if e.category_id})
    project_map: dict[Any, str] = {}
    category_map: dict[Any, str] = {}

    if all_project_ids:
        projects = await Project.find(In(Project.id, all_project_ids), Project.is_deleted == False).to_list()
        project_map = {p.id: p.name for p in projects}
    if all_category_ids:
        categories = await Category.find(In(Category.id, all_category_ids), Category.is_deleted == False).to_list()
        category_map = {c.id: c.category_name for c in categories}

    entries_map: dict[UUID, list[dict[str, Any]]] = {}
    for e in entries:
        d = e.model_dump()
        d["project_name"] = project_map.get(e.project_id)
        d["category_name"] = category_map.get(e.category_id)
        d["project_or_activity"] = d["project_name"] or d["category_name"] or d.get("task")
        entries_map.setdefault(e.timesheet_id, []).append(d)

    result = []
    for h in headers:
        u = user_map.get(h.user_id)
        result.append({
            "id": str(h.id),
            "user_id": str(h.user_id),
            "employee_code": u.employee_code if u else "",
            "full_name": u.full_name if u else "",
            "user_role": u.role.role_name if u and u.role else "USER",
            "status": h.status,
            "total_hours": h.total_hours,
            "week_start": h.week_start,
            "week_end": h.week_end,
            "admin_comment": h.admin_comment,
            "entries": entries_map.get(h.id, []),
        })

    return result

@router.post("/{id}/approve")
async def approve_timesheet(
    id: UUID,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    prev_status = header.status
        
    if header.status != "Submitted":
        raise HTTPException(status_code=400, detail="Timesheet is not in Submitted state")

    # Permission check
    if current_user.role.role_name == "ADMIN":
        target_user = await User.find_one(User.id == header.user_id, fetch_links=True)
        if not target_user or not target_user.role or target_user.role.role_name != "USER":
            raise HTTPException(status_code=403, detail="Admin may only reject regular user timesheets")
    elif current_user.role.role_name == "SUPER_ADMIN":
        target_user = await User.find_one(User.id == header.user_id, fetch_links=True)
        if target_user and target_user.role and target_user.role.role_name == "USER":
            raise HTTPException(status_code=403, detail="Super Admin has read-only visibility for regular users")

    header.status = "Approved"
    header.admin_comment = "Approved by admin"
    await header.save()

    await AuditLog(
        user_id=current_user.id,
        target_user_id=header.user_id,
        action="Approved",
        module="TimesheetApprovals",
        old_value=f"status={prev_status}",
        new_value=f"status={header.status}; admin_comment={header.admin_comment}",
    ).insert()

    # Add notification
    target_user = await User.find_one(User.id == header.user_id)
    await create_global_notification(
        type="info",
        title="Timesheet Approved",
        message=f"Your timesheet for the week starting {header.week_start} has been approved.",
        link=f"/weekly-submission?week_id={header.id}",
        target_user=target_user,
        actor=current_user
    )

    return {"msg": "Timesheet approved successfully"}

@router.post("/{id}/return")
async def return_timesheet(
    id: UUID,
    approval_in: TimesheetApproval,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    prev_status = header.status
        
    if header.status != "Submitted":
        raise HTTPException(status_code=400, detail="Timesheet is not in Submitted state")
        
    header.status = "Returned"
    header.admin_comment = approval_in.admin_comment
    await header.save()

    await AuditLog(
        user_id=current_user.id,
        target_user_id=header.user_id,
        action="Returned",
        module="TimesheetApprovals",
        old_value=f"status={prev_status}",
        new_value=f"status={header.status}; admin_comment={header.admin_comment}",
    ).insert()

    # Add notification
    target_user = await User.find_one(User.id == header.user_id)
    await create_global_notification(
        type="warning",
        title="Timesheet Returned",
        message=f"Your timesheet for the week starting {header.week_start} has been returned for correction.",
        link=f"/weekly-submission?week_id={header.id}",
        target_user=target_user,
        actor=current_user
    )

    return {"msg": "Timesheet returned to user for changes"}


@router.post("/{id}/reject")
async def reject_timesheet(
    id: UUID,
    approval_in: TimesheetApproval,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    prev_status = header.status

    if header.status != "Submitted":
        raise HTTPException(status_code=400, detail="Timesheet is not in Submitted state")

    if current_user.role.role_name == "ADMIN":
        target_user = await User.find_one(User.id == header.user_id, fetch_links=True)
        if not target_user or not target_user.role or target_user.role.role_name != "USER":
            raise HTTPException(status_code=403, detail="Admin may only reject regular user timesheets")
    
    # SUPER_ADMIN can reject anyone's timesheet

    header.status = "Rejected"
    header.admin_comment = approval_in.admin_comment or "Rejected by admin"
    await header.save()

    await AuditLog(
        user_id=current_user.id,
        target_user_id=header.user_id,
        action="Rejected",
        module="TimesheetApprovals",
        old_value=f"status={prev_status}",
        new_value=f"status={header.status}; admin_comment={header.admin_comment}",
    ).insert()

    # Add notification
    target_user = await User.find_one(User.id == header.user_id)
    if target_user:
        await create_global_notification(
            type="warning",
            title="Timesheet Rejected",
            message=f"Your timesheet for the week starting {header.week_start} has been rejected.",
            link=f"/weekly-submission?week_id={header.id}",
            target_user=target_user,
            actor=current_user
        )

    return {"msg": "Timesheet rejected and returned to user"}
