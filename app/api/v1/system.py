from datetime import date, timedelta, datetime
from collections import defaultdict
from uuid import UUID
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from beanie.operators import In, And, GTE, LTE

from app.api import deps
from app.models.notification import Notification
from app.models.user import User
from app.models.role import Role
from app.models.system_setting import SystemSetting
from app.models.audit_log import AuditLog
from app.models.project import Project, ProjectAssignment
from app.models.category import Category
from app.models.leave import Leave
from app.models.attendance import Attendance
from app.models.timesheet import TimesheetHeader, TimesheetEntry
from app.db.session import client as db_client
from app.schemas.system_setting import SystemSettingUpdate

router = APIRouter()

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
    # 1. Notify target user
    if target_user:
        await Notification(
            user=target_user,
            type=type,
            title=title,
            message=message,
            link=link
        ).insert()

    # 2. Notify all Super Admins
    super_admin_role = await Role.find_one(Role.role_name == "SUPER_ADMIN")
    if super_admin_role:
        super_admins = await User.find(User.role.id == super_admin_role.id, User.is_deleted == False).to_list()
        for sa in super_admins:
            # Avoid duplicate if target_user is a super admin
            if target_user and sa.id == target_user.id:
                continue
                
            actor_name = actor.full_name if actor else (target_user.full_name if target_user else 'System')
            await Notification(
                user=sa,
                type=type,
                title=f"[Global] {title}",
                message=f"Activity by {actor_name}: {message}",
                link=link
            ).insert()



async def _get_or_create_settings() -> SystemSetting:
    s = await SystemSetting.find_all().first_or_none()
    if not s:
        s = SystemSetting()
        await s.insert()
    return s


@router.get("/settings")
async def read_system_settings(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    s = await _get_or_create_settings()
    return {
        "expected_hours_per_day": s.expected_hours_per_day,
        "max_daily_hours": s.max_daily_hours,
        "weekly_submission_day": s.weekly_submission_day,
        "lock_week_after_approval": s.lock_week_after_approval,
        "updated_at": s.updated_at,
    }


@router.put("/settings")
async def update_system_settings(
    *,
    payload: SystemSettingUpdate,
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    s = await _get_or_create_settings()
    old_value = {
        "expected_hours_per_day": s.expected_hours_per_day,
        "max_daily_hours": s.max_daily_hours,
        "weekly_submission_day": s.weekly_submission_day,
        "lock_week_after_approval": s.lock_week_after_approval,
    }
    s.expected_hours_per_day = payload.expected_hours_per_day
    s.max_daily_hours = payload.max_daily_hours
    s.weekly_submission_day = payload.weekly_submission_day
    s.lock_week_after_approval = payload.lock_week_after_approval
    s.updated_at = datetime.utcnow()
    await s.save()

    await AuditLog(
        user_id=current_user.id,
        action="Updated",
        module="SystemSettings",
        old_value=str(old_value),
        new_value=str(payload.model_dump()),
    ).insert()

    return {"msg": "Settings updated"}


@router.get("/info")
async def read_system_info(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    total_users = len(await User.find(User.is_deleted == False).to_list())
    active_projects = len(await Project.find(Project.is_deleted == False).to_list())
    categories = len(await Category.find(Category.is_deleted == False).to_list())
    holidays = await db_client.timesheet_db.holidays.count_documents({}) if db_client else 0
    last_audit = await AuditLog.find_all().sort(-AuditLog.created_at).first_or_none()
    return {
        "system_version": "v1.0",
        "total_users": total_users,
        "active_projects": active_projects,
        "categories": categories,
        "holidays": holidays,
        "last_backup": last_audit.created_at if last_audit else None,
    }


@router.get("/audit-logs")
async def read_audit_logs(
    current_user: User = Depends(deps.get_current_active_superuser),
    limit: int = 50,
) -> Any:
    logs = await AuditLog.find_all().sort(-AuditLog.created_at).limit(limit).to_list()
    users = await User.find(In(User.id, [l.user_id for l in logs]), fetch_links=True).to_list() if logs else []
    user_map = {u.id: u for u in users}
    return [
        {
            "id": str(l.id),
            "time": l.created_at,
            "user": user_map.get(l.user_id).full_name if user_map.get(l.user_id) else "Unknown",
            "module": l.module,
            "action": l.action,
            "detail": l.new_value or l.old_value or "",
        }
        for l in logs
    ]


def _week_bounds(target_date: date) -> tuple[date, date]:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week


@router.get("/dashboard-stats")
async def get_dashboard_stats(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    # 1. Basic counts
    if current_user.role.role_name == "SUPER_ADMIN":
        pending_approvals = await TimesheetHeader.find(TimesheetHeader.status == "Submitted").count()
    else:
        reporting_users = await User.find(User.reporting_admin_id == current_user.id).to_list()
        reporting_ids = [u.id for u in reporting_users]
        pending_approvals = await TimesheetHeader.find(
            TimesheetHeader.status == "Submitted",
            In(TimesheetHeader.user_id, reporting_ids)
        ).count()

    total_users = await User.find(User.is_deleted == False).count()
    active_projects = await Project.find(Project.is_deleted == False).count()
    
    # 2. Compliance (This week)
    today = date.today()
    week_start, _ = _week_bounds(today)
    submitted_this_week = await TimesheetHeader.find(
        TimesheetHeader.week_start == week_start,
        In(TimesheetHeader.status, ["Submitted", "Approved"])
    ).count()
    
    compliance_pct = round((submitted_this_week / total_users * 100), 1) if total_users > 0 else 0
    
    # 3. Team Utilization (Top 10 users by hours this week)
    headers_this_week = await TimesheetHeader.find(TimesheetHeader.week_start == week_start).to_list()
    user_ids = list({h.user_id for h in headers_this_week})
    users = await User.find(In(User.id, user_ids)).to_list()
    user_map = {u.id: (u.full_name or u.employee_code or u.email) for u in users}
    
    # Aggregate hours by user (in case of duplicates)
    util_map = defaultdict(float)
    for h in headers_this_week:
        util_map[h.user_id] += float(h.total_hours)

    team_utilization = [
        {"name": user_map.get(uid, "Deleted User"), "hours": round(hours, 2)}
        for uid, hours in util_map.items()
    ]
    team_utilization = sorted(team_utilization, key=lambda x: x["hours"], reverse=True)[:10]

    # 4. Project Effort (Total hours per project - last 30 days)
    start_30 = today - timedelta(days=30)
    entries_30 = await TimesheetEntry.find(
        TimesheetEntry.date >= start_30,
        TimesheetEntry.entry_type == "Project",
        TimesheetEntry.is_deleted == False
    ).to_list()
    
    proj_effort_map = defaultdict(float)
    for e in entries_30:
        if e.project_id:
            proj_effort_map[e.project_id] += float(e.hours)
            
    project_ids = list(proj_effort_map.keys())
    projects = await Project.find(In(Project.id, project_ids)).to_list()
    proj_name_map = {p.id: p.name for p in projects}
    
    project_effort = [
        {"name": proj_name_map.get(pid, f"Project {str(pid)[:6]}"), "value": round(hours, 2)}
        for pid, hours in proj_effort_map.items()
    ]
    project_effort = sorted(project_effort, key=lambda x: x["value"], reverse=True)[:5]

    # 5. Weekly trend (Last 6 weeks)
    weekly_trend = []
    for i in range(5, -1, -1):
        target_v = today - timedelta(weeks=i)
        ws, _ = _week_bounds(target_v)
        sub_count = await TimesheetHeader.find(
            TimesheetHeader.week_start == ws,
            In(TimesheetHeader.status, ["Submitted", "Approved"])
        ).count()
        weekly_trend.append({
            "week": ws.strftime("%d %b"),
            "submitted": sub_count,
            "total": total_users
        })

    return {
        "pending_approvals": pending_approvals,
        "total_users": total_users,
        "active_projects": active_projects,
        "compliance_pct": compliance_pct,
        "submitted_this_week": submitted_this_week,
        "team_utilization": team_utilization,
        "project_effort": project_effort,
        "weekly_trend": weekly_trend
    }


def _iso_date_or_default(value: str | None, default_value: date) -> date:
    if not value:
        return default_value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")


def _user_basic(u: User) -> dict[str, Any]:
    # Role may be a Link or fetched document depending on the query.
    role_name = getattr(getattr(u, "role", None), "role_name", None)
    return {
        "id": str(u.id),
        "full_name": getattr(u, "full_name", None) or "",
        "employee_code": getattr(u, "employee_code", None) or "",
        "email": str(getattr(u, "email", "")) if getattr(u, "email", None) is not None else "",
        "department": getattr(u, "department", None),
        "designation": getattr(u, "designation", None),
        "role": role_name,
        "reporting_admin_id": str(getattr(u, "reporting_admin_id", None)) if getattr(u, "reporting_admin_id", None) is not None else None,
    }


@router.get("/org-tree")
async def get_org_tree_for_superadmin(
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    # Build a full recursive tree for Super Admin
    all_users = await User.find(User.is_deleted == False, fetch_links=True).to_list()
    
    # Map users by reporting_admin_id for fast lookup
    tree_map = defaultdict(list)
    for u in all_users:
        if u.reporting_admin_id:
            tree_map[str(u.reporting_admin_id)].append(u)
            
    # Functional grouping (by department)
    dept_map = defaultdict(list)
    for u in all_users:
        dept = u.department or "Unassigned"
        dept_map[dept].append(_user_basic(u))

    def build_node(user: User):
        node = _user_basic(user)
        children = tree_map.get(str(user.id), [])
        if children:
            node["children"] = [build_node(c) for c in children]
        return node

    # Roots are users with no reporting_admin_id or whose reporting_admin_id is not in all_users
    user_ids = {str(u.id) for u in all_users}
    roots = [u for u in all_users if not u.reporting_admin_id or str(u.reporting_admin_id) not in user_ids]
    
    hierarchical_tree = [build_node(r) for r in roots]
    functional_tree = [{"department": dept, "users": users} for dept, users in dept_map.items()]

    return {
        "hierarchical_tree": hierarchical_tree,
        "functional_tree": functional_tree
    }


@router.get("/approval-logs")
async def get_approval_logs_for_superadmin(
    current_user: User = Depends(deps.get_current_active_superuser),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    approval_modules = ["LeaveApprovals", "AttendanceApprovals", "TimesheetApprovals"]
    logs = await AuditLog.find(
        In(AuditLog.module, approval_modules),
    ).sort(-AuditLog.created_at).limit(limit).to_list()

    # Map approver ids to user names
    approver_ids = list({l.user_id for l in logs if getattr(l, "user_id", None) is not None})
    approvers = await User.find(In(User.id, approver_ids), fetch_links=False).to_list() if approver_ids else []
    approver_map = {u.id: u for u in approvers}

    return [
        {
            "id": str(l.id),
            "time": l.created_at,
            "approver": (approver_map.get(l.user_id).full_name if approver_map.get(l.user_id) else "Unknown"),
            "approver_user_id": str(l.user_id) if getattr(l, "user_id", None) is not None else None,
            "target_user_id": str(l.target_user_id) if getattr(l, "target_user_id", None) is not None else None,
            "action": l.action,
            "module": l.module,
            "detail": l.new_value or l.old_value or "",
        }
        for l in logs
    ]


@router.get("/user-visibility")
async def get_user_visibility_snapshot(
    user_id: str = Query(...),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    # Parse dates / validate input early
    try:
        target_uuid = UUID(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    today = date.today()
    default_from = today - timedelta(days=30)
    start_d = _iso_date_or_default(from_date, default_from)
    end_d = _iso_date_or_default(to_date, today)

    target = await User.find_one(User.id == target_uuid, fetch_links=True)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Projects (multi-project assignments)
    assignments = await ProjectAssignment.find(ProjectAssignment.user_id == target_uuid).to_list()
    project_ids = [a.project_id for a in assignments]
    projects = await Project.find(In(Project.id, project_ids), Project.is_deleted == False).to_list() if project_ids else []
    proj_map = {p.id: p for p in projects}
    user_projects = []
    for a in assignments:
        p = proj_map.get(a.project_id)
        if p:
            user_projects.append({
                "id": str(p.id),
                "project_code": p.project_code,
                "name": p.name,
                "expected_completion_date": p.expected_completion_date.isoformat() if getattr(p, "expected_completion_date", None) else None,
                "status": p.status,
                "billable_type": p.billable_type,
            })

    # Leave + Attendance
    from_iso = start_d.isoformat()
    to_iso = end_d.isoformat()

    leaves = await Leave.find(
        Leave.user.id == target_uuid,
        Leave.to_date >= from_iso,
        Leave.from_date <= to_iso,
        fetch_links=True,
    ).sort(-Leave.applied_on).limit(10).to_list()  # type: ignore[attr-defined]

    # Attendance date is stored as string YYYY-MM-DD
    attendances = await Attendance.find(
        Attendance.user.id == target_uuid,
        Attendance.date >= from_iso,
        Attendance.date <= to_iso,
        fetch_links=True,
    ).sort(-Attendance.date).limit(10).to_list()

    # Timesheet entries: need to resolve timesheet headers first (user_id -> header ids)
    headers = await TimesheetHeader.find(
        TimesheetHeader.user_id == target_uuid,
        TimesheetHeader.week_start <= end_d,
        TimesheetHeader.week_end >= start_d,
    ).to_list()
    header_ids = [h.id for h in headers]

    daily_entries: list[dict[str, Any]] = []
    if header_ids:
        entries = await TimesheetEntry.find(
            In(TimesheetEntry.timesheet_id, header_ids),
            TimesheetEntry.date >= start_d,
            TimesheetEntry.date <= end_d,
            TimesheetEntry.is_deleted == False,
        ).limit(50).to_list()

        project_ids = list({e.project_id for e in entries if getattr(e, "project_id", None)})
        category_ids = list({e.category_id for e in entries if getattr(e, "category_id", None)})

        project_map: dict[Any, str] = {}
        category_map: dict[Any, str] = {}
        if project_ids:
            ps = await Project.find(In(Project.id, project_ids), Project.is_deleted == False).to_list()
            project_map = {p.id: p.name for p in ps}
        if category_ids:
            cs = await Category.find(In(Category.id, category_ids), Category.is_deleted == False).to_list()
            category_map = {c.id: c.category_name for c in cs}

        for e in entries:
            d = e.model_dump()
            # Convert IDs to strings to keep JSON serialization stable.
            d["id"] = str(e.id)
            d["timesheet_id"] = str(getattr(e, "timesheet_id", None))
            if getattr(e, "project_id", None) is not None:
                d["project_id"] = str(e.project_id)
            if getattr(e, "category_id", None) is not None:
                d["category_id"] = str(e.category_id)
            d["project_name"] = project_map.get(e.project_id)
            d["category_name"] = category_map.get(e.category_id)
            d["project_or_activity"] = d["project_name"] or d["category_name"] or d.get("task") or None
            daily_entries.append(d)

    weekly_timesheets = [
        {
            "id": str(h.id),
            "week_start": h.week_start.isoformat(),
            "week_end": h.week_end.isoformat(),
            "status": h.status,
            "total_hours": h.total_hours,
            "admin_comment": h.admin_comment,
        }
        for h in headers
    ]

    # Approval logs relevant to this user's records
    approval_modules = ["LeaveApprovals", "AttendanceApprovals", "TimesheetApprovals"]
    logs = await AuditLog.find(
        AuditLog.target_user_id == target_uuid,
        In(AuditLog.module, approval_modules),
    ).sort(-AuditLog.created_at).limit(20).to_list()

    approver_ids = list({l.user_id for l in logs if getattr(l, "user_id", None) is not None})
    approvers = await User.find(In(User.id, approver_ids)).to_list() if approver_ids else []
    approver_map = {u.id: u.full_name for u in approvers}

    approval_logs = [
        {
            "id": str(l.id),
            "time": l.created_at,
            "approver": approver_map.get(l.user_id, "Unknown"),
            "action": l.action,
            "module": l.module,
            "detail": l.new_value or l.old_value or "",
        }
        for l in logs
    ]

    # Sanitize leave/attendance records for UI (avoid Link serialization issues)
    leave_items = []
    for l in leaves:
        ld = l.model_dump()
        ld["id"] = str(l.id)
        ld["from"] = l.from_date
        ld["to"] = l.to_date
        ld["type"] = l.leave_type
        ld["user_id"] = str(target_uuid)
        # Approver can be Link or fetched document; expose id only.
        ld.pop("user", None)
        ld.pop("approved_by", None)
        ld["approved_by_id"] = str(getattr(l.approved_by, "id", None)) if getattr(l, "approved_by", None) is not None else None
        leave_items.append(ld)

    attendance_items = []
    for r in attendances:
        rd = r.model_dump()
        rd["id"] = str(r.id)
        rd["user_id"] = str(target_uuid)
        rd.pop("user", None)
        rd.pop("approved_by", None)
        rd["approved_by_id"] = str(getattr(r.approved_by, "id", None)) if getattr(r, "approved_by", None) is not None else None
        attendance_items.append(rd)

    return {
        "user": _user_basic(target),
        "projects": user_projects,
        "leaves": leave_items,
        "attendances": attendance_items,
        "daily_timesheet_entries": daily_entries,
        "weekly_timesheets": weekly_timesheets,
        "approval_logs": approval_logs,
        "range": {"from_date": start_d.isoformat(), "to_date": end_d.isoformat()},
    }


@router.get("/global-activity")
async def get_global_activity(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    project_id: Optional[UUID] = Query(None),
    department: Optional[str] = Query(None),
    role_name: Optional[str] = Query(None),
    current_user: User = Depends(deps.get_current_active_superuser),
) -> Any:
    # 1. Base user filter
    user_query = {"is_deleted": False}
    if department:
        user_query["department"] = department
    
    users = await User.find(user_query, fetch_links=True).to_list()
    
    if role_name:
        users = [u for u in users if u.role and u.role.role_name == role_name]
    
    if not users:
        return []

    user_ids = [u.id for u in users]
    user_map = {u.id: u for u in users}

    # 2. Date filters
    today = date.today()
    s_date = start_date or (today - timedelta(days=7))
    e_date = end_date or today
    s_iso = s_date.isoformat()
    e_iso = e_date.isoformat()

    activities = []

    # 3. Fetch Attendance
    attendance_raw = {
        "user.$id": {"$in": user_ids},
        "date": {"$gte": s_iso, "$lte": e_iso}
    }
    attendances = await Attendance.find(attendance_raw, fetch_links=True).to_list()
    for att in attendances:
        activities.append({
            "id": str(att.id),
            "type": "Attendance",
            "date": att.date,
            "user_id": str(att.user.id) if att.user else None,
            "user_name": att.user.full_name if att.user else "Unknown",
            "status": att.status,
            "detail": f"{att.check_in or '--'} to {att.check_out or '--'} ({att.hours or 0} hrs)",
            "approval_status": att.approval_status or "pending",
            "created_at": att.date, # Fallback
        })

    # 4. Fetch Leaves
    leave_raw = {
        "user.$id": {"$in": user_ids},
        "$or": [
            {"from_date": {"$gte": s_iso, "$lte": e_iso}},
            {"to_date": {"$gte": s_iso, "$lte": e_iso}}
        ]
    }
    leaves = await Leave.find(leave_raw, fetch_links=True).to_list()
    for l in leaves:
        activities.append({
            "id": str(l.id),
            "type": "Leave",
            "date": l.from_date,
            "user_id": str(l.user.id) if l.user else None,
            "user_name": l.user.full_name if l.user else "Unknown",
            "status": l.status,
            "detail": f"{l.leave_type}: {l.from_date} to {l.to_date} ({l.days} days)",
            "reason": l.reason,
            "created_at": l.applied_on,
        })

    # 5. Fetch Timesheets (Weekly Headers)
    ts_query = And(In(TimesheetHeader.user_id, user_ids), GTE(TimesheetHeader.week_start, s_date), LTE(TimesheetHeader.week_start, e_date))
    headers = await TimesheetHeader.find(ts_query).to_list()
    header_ids = [h.id for h in headers]
    
    for h in headers:
        u = user_map.get(h.user_id)
        activities.append({
            "id": str(h.id),
            "type": "Timesheet",
            "date": h.week_start.isoformat(),
            "user_id": str(h.user_id),
            "user_name": u.full_name if u else "Unknown",
            "status": h.status,
            "detail": f"Weekly: {h.total_hours} total hours",
            "created_at": h.week_start.isoformat(),
        })

    # 6. Fetch Daily Entries (Using header_ids from above)
    if header_ids:
        entry_query = And(In(TimesheetEntry.timesheet_id, header_ids), GTE(TimesheetEntry.date, s_date), LTE(TimesheetEntry.date, e_date))
        if project_id:
            entry_query = And(entry_query, TimesheetEntry.project_id == project_id)
        
        entries = await TimesheetEntry.find(entry_query).to_list()
        
        # Pre-fetch projects for names
        p_ids = list({e.project_id for e in entries if e.project_id})
        projects = await Project.find(In(Project.id, p_ids)).to_list() if p_ids else []
        p_map = {p.id: p.name for p in projects}

        for e in entries:
            # We need the user_id for entries. Since they don't have it, we find it from header_ids
            # but for performance, we can map header_id to user_id
            header_to_user = {h.id: h.user_id for h in headers}
            u_id = header_to_user.get(e.timesheet_id)
            u = user_map.get(u_id)
            p_name = p_map.get(e.project_id, "N/A")
            activities.append({
                "id": str(e.id),
                "type": "DailyEntry",
                "date": e.date.isoformat(),
                "user_id": str(u_id) if u_id else None,
                "user_name": u.full_name if u else "Unknown",
                "project_name": p_name,
                "detail": f"{p_name}: {e.hours} hrs - {e.task[:50] if e.task else ''}",
                "created_at": e.date.isoformat(),
            })

    # 7. Fetch Approval Logs
    log_query = And(GTE(AuditLog.created_at, datetime.combine(s_date, datetime.min.time())), LTE(AuditLog.created_at, datetime.combine(e_date, datetime.max.time())))
    approval_modules = ["LeaveApprovals", "AttendanceApprovals", "TimesheetApprovals"]
    log_query = And(log_query, In(AuditLog.module, approval_modules))
    
    logs = await AuditLog.find(log_query).to_list()
    
    # Map approver ids
    approver_ids = list({l.user_id for l in logs})
    approvers = await User.find(In(User.id, approver_ids)).to_list() if approver_ids else []
    app_map = {u.id: u.full_name for u in approvers}

    for l in logs:
        target_u = user_map.get(l.target_user_id)
        if target_u or not l.target_user_id: # Show all or filtered
            activities.append({
                "id": str(l.id),
                "type": "Approval",
                "date": l.created_at.date().isoformat(),
                "user_id": str(l.user_id),
                "user_name": app_map.get(l.user_id, "System"),
                "target_user_id": str(l.target_user_id) if l.target_user_id else None,
                "target_user_name": target_u.full_name if target_u else "N/A",
                "status": l.action,
                "detail": f"{l.module}: {l.action} for {target_u.full_name if target_u else 'Unknown'}",
                "created_at": l.created_at.isoformat(),
            })

    # Filter by project_id if specified (only for DailyEntry and Timesheet entries if they had project_id)
    if project_id:
        activities = [a for a in activities if a.get("project_id") == str(project_id) or a["type"] != "DailyEntry"]

    # Sort by created_at desc
    activities.sort(key=lambda x: x["created_at"], reverse=True)

    return activities
