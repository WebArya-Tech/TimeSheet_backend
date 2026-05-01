from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from uuid import UUID
from datetime import datetime, date, timedelta
from beanie.operators import In, Or

from app.api import deps
from app.models.user import User
from app.models.attendance import Attendance
from app.models.notification import Notification
from app.models.role import Role
from app.models.audit_log import AuditLog
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate, AttendanceApprovalUpdate, AttendanceMarkRequest
import traceback
import logging
from app.api.v1.system import create_global_notification

router = APIRouter()


def _link_id(link: Any) -> Optional[str]:
    if not link:
        return None
    if hasattr(link, "id"):
        return str(link.id)
    return str(link)


def _today_str() -> str:
    return date.today().isoformat()


def _now_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def _hours_between(start_hhmm: str, end_hhmm: str) -> float:
    start = datetime.strptime(start_hhmm, "%H:%M")
    end = datetime.strptime(end_hhmm, "%H:%M")
    if end < start:
        end = end + timedelta(days=1)
    secs = (end - start).total_seconds()
    return round(secs / 3600, 2)


def _attendance_to_dict(record: Attendance, user_id: Optional[UUID] = None) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "user_id": str(user_id) if user_id else _link_id(getattr(record, "user", None)),
        "date": record.date,
        "status": record.status,
        "check_in": record.check_in,
        "check_out": record.check_out,
        "hours": record.hours,
        "note": record.note,
        # approval_status may be None in older records; default to 'pending'
        "approval_status": (getattr(record, "approval_status", None) or "pending").lower(),
        "approver_comment": getattr(record, "approver_comment", None),
        "approved_by_id": _link_id(getattr(record, "approved_by", None)),
    }

@router.get("/my")
async def read_my_attendance(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None), # 0-indexed for frontend compatibility
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    # Filter by user
    query = {"user.$id": current_user.id}
    if year is not None and month is not None:
        # e.g., ^2026-03
        prefix = f"{year}-{str(month + 1).zfill(2)}"
        query["date"] = {"$regex": f"^{prefix}"}
        
    records = await Attendance.find(query).to_list()
    
    results = []
    for r in records:
        rd = _attendance_to_dict(r, current_user.id)
        # Map for UI
        rd["checkIn"] = rd.get("check_in")
        rd["checkOut"] = rd.get("check_out")
        # Extract day from YYYY-MM-DD
        rd["dateNum"] = int(rd["date"].split("-")[2]) 
        results.append(rd)
    return JSONResponse(content=jsonable_encoder(results))

@router.post("/", response_model=Any)
async def create_attendance(
    *,
    record_in: AttendanceCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    # Check if exists for same user and date
    existing = await Attendance.find_one(Attendance.user.id == current_user.id, Attendance.date == record_in.date)
    if existing:
        # Update existing
        existing.status = record_in.status
        existing.check_in = record_in.check_in
        existing.check_out = record_in.check_out
        existing.hours = record_in.hours
        existing.note = record_in.note
        existing.approval_status = "pending"
        await existing.save()
        return _attendance_to_dict(existing, current_user.id)
        
    db_record = Attendance(
        user=current_user,
        date=record_in.date,
        status=record_in.status,
        check_in=record_in.check_in,
        check_out=record_in.check_out,
        hours=record_in.hours,
        note=record_in.note,
        approval_status="pending"
    )
    await db_record.insert()
    return _attendance_to_dict(db_record, current_user.id)

@router.put("/record/{id}", response_model=Any)
async def update_attendance(
    *,
    id: UUID,
    record_in: AttendanceUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    record = await Attendance.find_one(Attendance.id == id)
    if not record:
        raise HTTPException(status_code=404, detail="Attendance not found")
        
    if record.approval_status in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Cannot edit attendance record once approval decision has been made")

    for k, v in record_in.model_dump(exclude_unset=True).items():
        setattr(record, k, v)
        
    await record.save()
    return _attendance_to_dict(record)


@router.get("/today", response_model=Any)
async def read_today_attendance(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    today = _today_str()
    record = await Attendance.find_one(Attendance.user.id == current_user.id, Attendance.date == today)
    if not record:
        return {
            "date": today,
            "status": "absent",
            "check_in": None,
            "check_out": None,
            "hours": 0,
            "note": None,
        }
    return _attendance_to_dict(record, current_user.id)


@router.post("/today/check-in", response_model=Any)
async def check_in_today(
    payload: AttendanceMarkRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    today = _today_str()
    now = _now_hhmm()
    record = await Attendance.find_one(Attendance.user.id == current_user.id, Attendance.date == today)
    if record and record.check_in:
        raise HTTPException(status_code=400, detail="Already checked in for today")

    if not record:
        record = Attendance(
            user=current_user,
            date=today,
            status=payload.status or "present",
            check_in=now,
            note=payload.note,
            approval_status="pending",
        )
        await record.insert()
    else:
        record.check_in = now
        record.status = payload.status or "present"
        record.approval_status = "pending"
        if payload.note:
            record.note = payload.note
        await record.save()
        
    await create_global_notification(
        type="info",
        title="Attendance Check-in",
        message=f"{current_user.full_name} checked in at {now}.",
        link="/attendance",
        actor=current_user
    )

    return _attendance_to_dict(record, current_user.id)


@router.post("/today/check-out")
async def check_out_today(
    payload: AttendanceMarkRequest,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    today = _today_str()
    now = _now_hhmm()
    record = await Attendance.find_one(Attendance.user.id == current_user.id, Attendance.date == today)
    if not record or not record.check_in:
        raise HTTPException(status_code=400, detail="Check in first")
    if record.check_out:
        raise HTTPException(status_code=400, detail="Already checked out for today")

    record.check_out = now
    record.hours = _hours_between(record.check_in, now)
    if payload.status:
        record.status = payload.status
    if payload.note:
        record.note = payload.note
    record.approval_status = "pending"
    await record.save()

    await create_global_notification(
        type="info",
        title="Attendance Check-out",
        message=f"{current_user.full_name} checked out at {now} ({record.hours} hrs).",
        link="/attendance",
        actor=current_user
    )
    return JSONResponse(content=jsonable_encoder(_attendance_to_dict(record, current_user.id)))


@router.get("/weekly-summary", response_model=Any)
async def weekly_summary(
    target_date: Optional[str] = None,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else date.today()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid target_date format, expected YYYY-MM-DD")
    week_start = d - timedelta(days=d.weekday())
    week_end = week_start + timedelta(days=6)

    records = await Attendance.find({
        "user.$id": current_user.id,
        "date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
    }).to_list()

    by_status: dict[str, int] = {}
    total_hours = 0.0
    for r in records:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        total_hours += float(r.hours or 0)

    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "total_hours": round(total_hours, 2),
        "days_present": by_status.get("present", 0) + by_status.get("wfh", 0),
        "days_absent": by_status.get("absent", 0),
        "days_leave": by_status.get("leave", 0),
        "days_late": by_status.get("late", 0),
        "records": [_attendance_to_dict(r, current_user.id) for r in records],
    }


@router.get("/pending", response_model=List[Any])
async def read_pending_attendances(
    current_user: User = Depends(deps.get_current_active_admin),
    status: str = "pending",
) -> Any:
    try:
        if status not in {"pending", "approved", "rejected"}:
            raise HTTPException(status_code=400, detail="Invalid attendance approval status")

        if status == "pending":
            status_query = Or(Attendance.approval_status == "pending", Attendance.approval_status == None)
        else:
            status_query = Attendance.approval_status == status

        if current_user.role.role_name == "SUPER_ADMIN":
            records = await Attendance.find(status_query, fetch_links=True).to_list()
        else:
            reporting_users = await User.find(User.reporting_admin_id == current_user.id, User.is_deleted == False).to_list()
            reporting_user_ids = [u.id for u in reporting_users] # Relaxed check to allow admins to see all reporting users
            
            if not reporting_user_ids:
                return []
                
            records = await Attendance.find(
                status_query, 
                In(Attendance.user.id, reporting_user_ids), 
                fetch_links=True
            ).to_list()

        results = []
        for record in records:
            data = _attendance_to_dict(record)
            if record.user:
                user_data = record.user.model_dump()
                # Clean up sensitive data for UI
                user_data.pop("hashed_password", None)
                data["user"] = user_data
            else:
                data["user"] = None
                
            if getattr(record, "approved_by", None):
                data["approved_by"] = record.approved_by.model_dump()
            results.append(data)
        return results
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error reading pending attendances")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{id}/status", response_model=Any)
async def update_attendance_approval_status(
    *,
    id: UUID,
    status_in: AttendanceApprovalUpdate,
    current_user: User = Depends(deps.get_current_admin_only),
) -> Any:
    try:
        record = await Attendance.find_one(Attendance.id == id, fetch_links=True)
        if not record:
            raise HTTPException(status_code=404, detail="Attendance record not found")

        prev_status = getattr(record, "approval_status", None)

        # Normalize incoming approval status and stored approval_status for case-insensitive checks
        incoming_status = (status_in.approval_status or "").strip().lower()
        if incoming_status not in {"approved", "rejected"}:
            raise HTTPException(status_code=400, detail="Invalid approval status")

        # Treat missing/None/empty approval_status as pending for backward compatibility
        current_status = (getattr(record, "approval_status", None) or "").strip().lower()
        if current_status and current_status != "pending":
            raise HTTPException(status_code=400, detail="Attendance record is not pending approval")

        if current_user.role.role_name == "ADMIN":
            if getattr(record, "user", None) and record.user.id == current_user.id:
                raise HTTPException(status_code=403, detail="Admin cannot approve their own attendance")
            
            # Check if target user is a regular User
            target_user = record.user
            if target_user and hasattr(target_user, "role"):
                target_role = target_user.role.role_name if hasattr(target_user.role, "role_name") else ""
                if target_role != "USER":
                    raise HTTPException(status_code=403, detail="Admin may only approve regular user attendance")
        
        elif current_user.role.role_name == "SUPER_ADMIN":
            # Super Admin can approve Admins, but not regular Users (they are read-only for users)
            target_user = record.user
            if target_user and hasattr(target_user, "role"):
                target_role = target_user.role.role_name if hasattr(target_user.role, "role_name") else ""
                if target_role == "USER":
                    raise HTTPException(status_code=403, detail="Super Admin has read-only visibility for regular users. Only Admins can approve them.")

        # Store approval status normalized to lowercase
        record.approval_status = incoming_status
        # Only ADMIN may perform approvals; normalise approver_comment accordingly
        record.approver_comment = status_in.approver_comment or (
            "Approved by admin" if incoming_status == "approved"
            else "Rejected by admin"
        )
        record.approved_by = current_user
        await record.save()

        target_uid = None
        if getattr(record, "user", None) is not None and hasattr(record.user, "id"):
            target_uid = record.user.id

        await AuditLog(
            user_id=current_user.id,
            target_user_id=target_uid,
            action=incoming_status.capitalize(),
            module="AttendanceApprovals",
            old_value=f"approval_status={prev_status}",
            new_value=f"approval_status={record.approval_status}; date={record.date}; approver_comment={record.approver_comment}",
        ).insert()

        # Add notification for the user
        try:
            target_user = None
            if getattr(record, "user", None) is not None:
                user_field = record.user
                if hasattr(user_field, "fetch") and callable(user_field.fetch):
                    target_user = await user_field.fetch()
                else:
                    target_user = user_field
            if target_user:
                await create_global_notification(
                    type="info" if status_in.approval_status == "approved" else "warning",
                    title=f"Attendance {status_in.approval_status.capitalize()} by Admin",
                    message=f"Your attendance for {record.date} has been {status_in.approval_status}.",
                    link=f"/attendance-approvals?record={record.id}",
                    target_user=target_user,
                    actor=current_user
                )
        except Exception:
            logging.exception("Failed to notify target user after attendance approval")

        return _attendance_to_dict(record)
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Error updating attendance approval status")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


