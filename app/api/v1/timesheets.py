from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from datetime import date, timedelta
from uuid import UUID
from beanie.operators import In

from app.api import deps
from app.models.timesheet import TimesheetHeader, TimesheetEntry
from app.models.project import ProjectAssignment
from app.models.project import Project
from app.models.category import Category
from app.models.user import User
from app.models.notification import Notification
from app.models.role import Role
from app.schemas.timesheet import TimesheetHeader as TimesheetHeaderSchema, TimesheetEntry as TimesheetEntrySchema, TimesheetEntryCreate
from app.api.v1.system import create_global_notification

router = APIRouter()


def _week_bounds(target_date: date) -> tuple[date, date]:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week


async def _serialize_entries(entries: list[TimesheetEntry]) -> list[dict[str, Any]]:
    if not entries:
        return []
    project_ids = list({e.project_id for e in entries if e.project_id})
    category_ids = list({e.category_id for e in entries if e.category_id})
    project_map: dict[Any, str] = {}
    category_map: dict[Any, str] = {}

    if project_ids:
        projects = await Project.find(In(Project.id, project_ids), Project.is_deleted == False).to_list()
        # use string keys for consistent lookup across types
        project_map = {str(p.id): p.name for p in projects}
    if category_ids:
        categories = await Category.find(In(Category.id, category_ids), Category.is_deleted == False).to_list()
        category_map = {str(c.id): c.category_name for c in categories}

    result: list[dict[str, Any]] = []
    for e in entries:
        d = e.model_dump()
        pid = str(e.project_id) if e.project_id else None
        cid = str(e.category_id) if e.category_id else None
        # include id strings for frontend
        d["project_id"] = pid
        d["category_id"] = cid
        d["project_name"] = project_map.get(pid) if pid else None
        d["category_name"] = category_map.get(cid) if cid else None
        # prefer project name, then category name, then task
        d["project_or_activity"] = d.get("project_name") or d.get("category_name") or d.get("task")
        # include expected completion if available from batch map
        d["expected_completion_date"] = None
        if pid and pid in project_map:
            # project_expected_map not available here; fetch below if needed
            pass
        # Fallback: if mapping missed a project/category, try single-document lookup
        if not d.get("project_name") and getattr(e, "project_id", None):
            try:
                p = await Project.find_one(Project.id == e.project_id, Project.is_deleted == False)
                if p:
                    d["project_name"] = p.name
                    if not d.get("project_or_activity"):
                        d["project_or_activity"] = p.name
                    if getattr(p, "expected_completion_date", None):
                        d["expected_completion_date"] = p.expected_completion_date.isoformat()
            except Exception:
                pass

        if not d.get("category_name") and getattr(e, "category_id", None):
            try:
                c = await Category.find_one(Category.id == e.category_id, Category.is_deleted == False)
                if c:
                    d["category_name"] = c.category_name
                    if not d.get("project_or_activity"):
                        d["project_or_activity"] = c.category_name
                    # categories typically don't have expected completion_date
            except Exception:
                pass

        result.append(d)
    return result


async def _recalculate_header_total(header_id: UUID) -> None:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == header_id)
    if not header:
        return
    entries = await TimesheetEntry.find(
        TimesheetEntry.timesheet_id == header_id,
        TimesheetEntry.is_deleted == False,
    ).to_list()
    header.total_hours = round(sum(float(e.hours or 0) for e in entries), 2)
    await header.save()

@router.get("/daily", response_model=List[Any])
async def get_daily_entries(
    target_date: date,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    # First get headers mapping to this user
    headers = await TimesheetHeader.find(TimesheetHeader.user_id == current_user.id).to_list()
    header_ids = [h.id for h in headers]
    
    entries = await TimesheetEntry.find(
        In(TimesheetEntry.timesheet_id, header_ids),
        TimesheetEntry.date == target_date,
        TimesheetEntry.is_deleted == False
    ).to_list()
    return await _serialize_entries(entries)

@router.post("/entry", response_model=TimesheetEntrySchema)
async def add_daily_entry(
    *,
    entry_in: TimesheetEntryCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    if entry_in.entry_type == "Project" and entry_in.project_id:
        # Relaxed check: Only check if project is active and exists
        project = await Project.find_one(Project.id == entry_in.project_id, Project.is_deleted == False)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.status != "Active":
            raise HTTPException(status_code=400, detail="This project is not currently active")
            
        if not entry_in.task or not entry_in.sub_task:
            raise HTTPException(status_code=400, detail="Task and Sub-task are required for project entries")
            
    # Prevent future-dated entries
    from datetime import date as _date
    if entry_in.date > _date.today():
        raise HTTPException(status_code=400, detail="Cannot add entries for future dates")

    # Find or create timesheet header for the week based on the date
    start_of_week, end_of_week = _week_bounds(entry_in.date)
    
    header = await TimesheetHeader.find_one(
        TimesheetHeader.user_id == current_user.id,
        TimesheetHeader.week_start == start_of_week
    )
    
    if not header:
        header = TimesheetHeader(
            user_id=current_user.id,
            week_start=start_of_week,
            week_end=end_of_week,
            status="Draft"
        )
        await header.insert()
        
    if header.status in ["Submitted", "Approved"]:
        raise HTTPException(status_code=400, detail="Timesheet has already been submitted or approved for this week")

    # Aggregate total hours for the day so far based on this header id and date
    pipeline = [
        {"$match": {
            "timesheet_id": header.id,
            "date": {"$eq": entry_in.date.isoformat()}, # depending on serialization
            "is_deleted": False
        }},
        {"$group": {"_id": None, "total": {"$sum": "$hours"}}}
    ]
    # For simplicity, calculate manually via find
    all_entries = await TimesheetEntry.find(
        TimesheetEntry.timesheet_id == header.id, 
        TimesheetEntry.date == entry_in.date,
        TimesheetEntry.is_deleted == False
    ).to_list()
    current_total = sum(e.hours for e in all_entries)
    
    if current_total + entry_in.hours > 24:
        raise HTTPException(status_code=400, detail="Total hours for the day cannot exceed 24")

    db_entry = TimesheetEntry(**entry_in.model_dump(), timesheet_id=header.id)
    await db_entry.insert()
    
    header.total_hours += entry_in.hours
    await header.save()
    
    return db_entry


@router.put("/entry/{id}", response_model=TimesheetEntrySchema)
async def update_daily_entry(
    *,
    id: UUID,
    entry_in: TimesheetEntryCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    db_entry = await TimesheetEntry.find_one(TimesheetEntry.id == id, TimesheetEntry.is_deleted == False)
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    header = await TimesheetHeader.find_one(TimesheetHeader.id == db_entry.timesheet_id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet header not found")
    if header.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot edit someone else's entry")
    if header.status in ["Submitted", "Approved"]:
        raise HTTPException(status_code=400, detail="Cannot edit submitted/approved timesheet")

    if entry_in.entry_type == "Project" and entry_in.project_id:
        # Relaxed check: Only check if project is active and exists
        project = await Project.find_one(Project.id == entry_in.project_id, Project.is_deleted == False)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.status != "Active":
            raise HTTPException(status_code=400, detail="This project is not currently active")

    # Prevent updating to a future date
    from datetime import date as _date
    if entry_in.date > _date.today():
        raise HTTPException(status_code=400, detail="Cannot set entry date in the future")

    day_entries = await TimesheetEntry.find(
        TimesheetEntry.timesheet_id == db_entry.timesheet_id,
        TimesheetEntry.date == entry_in.date,
        TimesheetEntry.is_deleted == False,
    ).to_list()
    others_total = sum(e.hours for e in day_entries if e.id != db_entry.id)
    if others_total + entry_in.hours > 24:
        raise HTTPException(status_code=400, detail="Total hours for the day cannot exceed 24")

    for field, value in entry_in.model_dump().items():
        setattr(db_entry, field, value)
    await db_entry.save()
    await _recalculate_header_total(db_entry.timesheet_id)
    return db_entry


@router.delete("/entry/{id}")
async def delete_daily_entry(
    *,
    id: UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    db_entry = await TimesheetEntry.find_one(TimesheetEntry.id == id, TimesheetEntry.is_deleted == False)
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    header = await TimesheetHeader.find_one(TimesheetHeader.id == db_entry.timesheet_id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet header not found")
    if header.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot delete someone else's entry")
    if header.status in ["Submitted", "Approved"]:
        raise HTTPException(status_code=400, detail="Cannot delete from submitted/approved timesheet")

    db_entry.is_deleted = True
    await db_entry.save()
    await _recalculate_header_total(db_entry.timesheet_id)
    return {"msg": "Entry deleted"}

@router.get("/week/{id}", response_model=TimesheetHeaderSchema)
async def get_weekly_timesheet(
    id: UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")
        
    if header.user_id != current_user.id and current_user.role.role_name not in ["ADMIN", "SUPER_ADMIN"]:
        raise HTTPException(status_code=403, detail="Not enough privileges")
        
    # Inject entries to return schema
    entries = await TimesheetEntry.find(TimesheetEntry.timesheet_id == header.id).to_list()
    
    # We must construct a dict or a model matching schema
    resp = header.model_dump()
    resp["entries"] = await _serialize_entries(entries)
    return resp

@router.post("/week/{id}/submit")
async def submit_timesheet(
    id: UUID,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")
        
    if header.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot submit someone else's timesheet")
        
    if header.status not in ["Draft", "Returned"]:
        raise HTTPException(status_code=400, detail="Can only submit Draft or Returned timesheets")
    
    # Prevent submitting for future weeks
    today = date.today()
    if header.week_start > today:
        raise HTTPException(status_code=400, detail="Cannot submit timesheets for future weeks")
        
    header.status = "Submitted"
    await header.save()
    if current_user.reporting_admin_id:
        admin_user = await User.find_one(User.id == current_user.reporting_admin_id)
        if admin_user:
            await create_global_notification(
                type="info",
                title="Weekly timesheet submitted",
                message=f"{current_user.full_name} submitted timesheet for {header.week_start} to {header.week_end}.",
                link=f"/weekly-submission?week_id={header.id}",
                target_user=admin_user,
                actor=current_user
            )
    return {"msg": "Timesheet submitted successfully"}


@router.put("/week/{id}/status")
async def update_timesheet_status(
    id: UUID,
    payload: dict,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    """Approve or return a weekly timesheet. Payload: { status: 'Approved'|'Returned', admin_comment?: str }"""
    header = await TimesheetHeader.find_one(TimesheetHeader.id == id)
    if not header:
        raise HTTPException(status_code=404, detail="Timesheet not found")

    status = (payload.get("status") or "").strip()
    if status not in {"Approved", "Returned"}:
        raise HTTPException(status_code=400, detail="Invalid timesheet status")

    # Set header status and admin comment
    header.status = status
    header.admin_comment = payload.get("admin_comment")
    await header.save()

    # Notify the owner
    user = await User.find_one(User.id == header.user_id)
    if user:
        await create_global_notification(
            type="info" if status == "Approved" else "warning",
            title=f"Timesheet {status}",
            message=f"Your timesheet for {header.week_start} to {header.week_end} has been {status}.",
            link=f"/weekly-submission?week_id={header.id}",
            target_user=user,
            actor=current_user
        )

    return {"msg": f"Timesheet {status} successfully"}


@router.get("/week-current", response_model=TimesheetHeaderSchema)
async def get_current_week_timesheet(
    target_date: Optional[date] = None,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    current_date = target_date or date.today()
    week_start, week_end = _week_bounds(current_date)

    header = await TimesheetHeader.find_one(
        TimesheetHeader.user_id == current_user.id,
        TimesheetHeader.week_start == week_start,
    )

    if not header:
        header = TimesheetHeader(
            user_id=current_user.id,
            week_start=week_start,
            week_end=week_end,
            status="Draft",
        )
        await header.insert()

    entries = await TimesheetEntry.find(
        TimesheetEntry.timesheet_id == header.id,
        TimesheetEntry.is_deleted == False,
    ).to_list()

    resp = header.model_dump()
    resp["entries"] = await _serialize_entries(entries)
    return resp


@router.get("/history/me")
async def get_my_timesheet_history(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    headers = await TimesheetHeader.find(TimesheetHeader.user_id == current_user.id).sort(-TimesheetHeader.week_start).skip(skip).limit(limit).to_list()
    return [h.model_dump() for h in headers]


@router.get("/team/week")
async def get_team_week_timesheets(
    target_date: Optional[date] = None,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    current_date = target_date or date.today()
    week_start, _ = _week_bounds(current_date)

    # SUPER_ADMIN sees all users; ADMIN sees only direct reports.
    if current_user.role.role_name == "SUPER_ADMIN":
        headers = await TimesheetHeader.find(TimesheetHeader.week_start == week_start).to_list()
    else:
        reporting_users = await User.find(User.reporting_admin_id == current_user.id).to_list()
        reporting_ids = [u.id for u in reporting_users]
        headers = await TimesheetHeader.find(
            TimesheetHeader.week_start == week_start,
            {"user_id": {"$in": reporting_ids}},
        ).to_list()

    if not headers:
        return []

    user_ids = [h.user_id for h in headers]
    users = await User.find({"id": {"$in": user_ids}}).to_list()
    user_map = {u.id: u for u in users}

    result = []
    for h in headers:
        u = user_map.get(h.user_id)
        result.append({
            "id": str(h.id),
            "user_id": str(h.user_id),
            "employee_code": u.employee_code if u else "N/A",
            "full_name": u.full_name if u else "Unknown User",
            "department": u.department if u else "General",
            "status": h.status,
            "total_hours": h.total_hours,
            "week_start": h.week_start,
            "week_end": h.week_end,
        })

    return result


    # end of normal routes


    # end of file
