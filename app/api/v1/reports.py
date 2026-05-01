from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from datetime import date, datetime, timedelta
from collections import defaultdict
import csv
from io import BytesIO, StringIO
from beanie.operators import In

from app.api import deps
from app.models.timesheet import TimesheetEntry, TimesheetHeader
from app.models.user import User
from app.models.project import Project
from app.models.category import Category

router = APIRouter()

@router.get("/user-hours")
async def get_user_hours_report(
    start_date: date,
    end_date: date,
    user_id: Optional[str] = None,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    # Aggregating manually via python due to lack of relational join support out of the box in
    # basic Beanie finds without custom aggregation pipelines.
    query_params = {"date": {"$gte": start_date, "$lte": end_date}}
    
    entries = await TimesheetEntry.find(query_params).to_list()
    header_ids = {e.timesheet_id for e in entries}
    headers = await TimesheetHeader.find(In(TimesheetHeader.id, list(header_ids))).to_list()
    
    user_ids = {h.user_id for h in headers}
    users = await User.find(In(User.id, list(user_ids))).to_list()
    
    # Filter by user_id if provided
    if user_id:
        users = [u for u in users if str(u.id) == user_id]
        entries = [e for e in entries if e.timesheet_id in {h.id for h in headers if str(h.user_id) == user_id}]
        
    user_map = {u.id: u.full_name for u in users}
    header_user_map = {h.id: h.user_id for h in headers}
    
    report = defaultdict(float)
    for entry in entries:
        h_uid = header_user_map.get(entry.timesheet_id)
        if h_uid in user_map:
            report[user_map[h_uid]] += entry.hours
            
    return [{"user": k, "total_hours": v} for k, v in report.items()]


@router.get("/export")
async def export_reports(
    period: str = Query(..., pattern="^(daily|weekly|monthly)$"),
    format: str = Query(..., pattern="^(csv|xlsx|pdf)$"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    # default window: last 30 days
    today = date.today()
    report_start = start_date or (today - timedelta(days=30))
    report_end = end_date or today
    if report_start > report_end:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")

    entries = await TimesheetEntry.find(
        {"date": {"$gte": report_start, "$lte": report_end}, "is_deleted": False}
    ).to_list()

    if not entries:
        rows = []
    else:
        header_ids = list({e.timesheet_id for e in entries})
        headers = await TimesheetHeader.find(In(TimesheetHeader.id, header_ids)).to_list()
        header_user = {h.id: h.user_id for h in headers}

        # role-based filtering
        if current_user.role.role_name == "USER":
            entries = [e for e in entries if header_user.get(e.timesheet_id) == current_user.id]
        elif current_user.role.role_name == "ADMIN":
            reporting_users = await User.find(User.reporting_admin_id == current_user.id).to_list()
            allowed_ids = {u.id for u in reporting_users} | {current_user.id}
            entries = [e for e in entries if header_user.get(e.timesheet_id) in allowed_ids]

        user_ids = {header_user.get(e.timesheet_id) for e in entries if header_user.get(e.timesheet_id)}
        users = await User.find(In(User.id, list(user_ids))).to_list()
        user_map = {u.id: u.full_name for u in users}

        grouped: dict[tuple[str, str], float] = defaultdict(float)
        for e in entries:
            uid = header_user.get(e.timesheet_id)
            if not uid:
                continue
            uname = user_map.get(uid, "Unknown")
            if period == "daily":
                key = e.date.strftime("%Y-%m-%d")
            elif period == "weekly":
                week_start = e.date - timedelta(days=e.date.weekday())
                key = f"{week_start.strftime('%Y-%m-%d')}"
            else:
                key = e.date.strftime("%Y-%m")
            grouped[(key, uname)] += float(e.hours)

        rows = [
            {"period": k[0], "user": k[1], "total_hours": round(v, 2)}
            for k, v in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1]))
        ]

    filename_base = f"{period}-report-{report_start.isoformat()}-to-{report_end.isoformat()}"

    if format == "csv":
        sio = StringIO()
        writer = csv.DictWriter(sio, fieldnames=["period", "user", "total_hours"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        content = sio.getvalue().encode("utf-8")
        return StreamingResponse(
            BytesIO(content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.csv"},
        )

    if format == "xlsx":
        try:
            from openpyxl import Workbook
        except Exception:
            raise HTTPException(status_code=500, detail="openpyxl is not installed")

        wb = Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(["Period", "User", "Total Hours"])
        for r in rows:
            ws.append([r["period"], r["user"], r["total_hours"]])
        xbio = BytesIO()
        wb.save(xbio)
        xbio.seek(0)
        return StreamingResponse(
            xbio,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename_base}.xlsx"},
        )

    # PDF
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        raise HTTPException(status_code=500, detail="reportlab is not installed")

    pbuf = BytesIO()
    c = canvas.Canvas(pbuf, pagesize=A4)
    width, height = A4
    y = height - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, f"{period.title()} Report ({report_start} to {report_end})")
    y -= 24
    c.setFont("Helvetica", 10)
    c.drawString(40, y, "Period")
    c.drawString(200, y, "User")
    c.drawString(430, y, "Total Hours")
    y -= 12
    c.line(40, y, 550, y)
    y -= 14
    for r in rows:
        if y < 50:
            c.showPage()
            y = height - 40
        c.drawString(40, y, str(r["period"]))
        c.drawString(200, y, str(r["user"])[:35])
        c.drawRightString(520, y, str(r["total_hours"]))
        y -= 14
    c.save()
    pbuf.seek(0)
    return StreamingResponse(
        pbuf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename_base}.pdf"},
    )


def _week_bounds(target_date: date) -> tuple[date, date]:
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week


@router.get("/project-effort")
async def get_project_effort_report(
    start_date: date,
    end_date: date,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    query = {
        "date": {"$gte": datetime.combine(start_date, datetime.min.time()), 
                 "$lte": datetime.combine(end_date, datetime.max.time())},
        "entry_type": "Project",
        "is_deleted": False
    }
    entries = await TimesheetEntry.find(query).to_list()
    
    project_ids = {e.project_id for e in entries if e.project_id}
    projects = await Project.find({"id": {"$in": list(project_ids)}}).to_list()
    proj_map = {p.id: p.name for p in projects}
    
    report = defaultdict(float)
    for e in entries:
        name = proj_map.get(e.project_id, "Unknown Project")
        report[name] += float(e.hours)
        
    return [{"project": k, "total_hours": round(v, 2)} for k, v in report.items()]


@router.get("/category-effort")
async def get_category_effort_report(
    start_date: date,
    end_date: date,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    query = {
        "date": {"$gte": datetime.combine(start_date, datetime.min.time()), 
                 "$lte": datetime.combine(end_date, datetime.max.time())},
        "entry_type": "Non-Project",
        "is_deleted": False
    }
    entries = await TimesheetEntry.find(query).to_list()
    
    category_ids = {e.category_id for e in entries if e.category_id}
    categories = await Category.find({"id": {"$in": list(category_ids)}}).to_list()
    cat_map = {c.id: c.category_name for c in categories}
    
    report = defaultdict(float)
    for e in entries:
        name = cat_map.get(e.category_id, "Unknown Category")
        report[name] += float(e.hours)
        
    return [{"category": k, "total_hours": round(v, 2)} for k, v in report.items()]


@router.get("/missing-submissions")
async def get_missing_submissions(
    target_date: date,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    start_of_week, _ = _week_bounds(target_date)
    
    # role based behavior
    if current_user.role.role_name == "SUPER_ADMIN":
        all_users = await User.find(User.is_deleted == False).to_list()
    else:
        all_users = await User.find(User.reporting_admin_id == current_user.id, User.is_deleted == False).to_list()
        
    submitted_headers = await TimesheetHeader.find(
        TimesheetHeader.week_start == start_of_week,
        {"status": {"$in": ["Submitted", "Approved"]}}
    ).to_list()
    
    submitted_user_ids = {h.user_id for h in submitted_headers}
    
    missing = [
        {"id": str(u.id), "full_name": u.full_name, "employee_code": u.employee_code}
        for u in all_users if u.id not in submitted_user_ids
    ]
    
    return missing
