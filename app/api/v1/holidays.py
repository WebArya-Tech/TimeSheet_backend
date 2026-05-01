from typing import Any, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException

from app.api import deps
from app.models.user import User
from app.models.holiday import Holiday
from app.schemas.holiday import Holiday as HolidaySchema, HolidayCreate, HolidayUpdate

router = APIRouter()


@router.get("", response_model=List[HolidaySchema])
async def read_holidays(
    skip: int = 0,
    limit: int = 200,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    holidays = await Holiday.find().sort(Holiday.holiday_date).skip(skip).limit(limit).to_list(length=limit)
    return holidays


@router.post("", response_model=HolidaySchema)
async def create_holiday(
    *,
    holiday_in: HolidayCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    exists = await Holiday.find_one(Holiday.holiday_date == holiday_in.holiday_date)
    if exists:
        raise HTTPException(status_code=400, detail="Holiday already exists for this date")

    db_holiday = Holiday(**holiday_in.model_dump())
    await db_holiday.insert()
    return db_holiday


@router.put("/{id}", response_model=HolidaySchema)
async def update_holiday(
    *,
    id: UUID,
    holiday_in: HolidayUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    holiday = await Holiday.find_one(Holiday.id == id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")

    update_data = holiday_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(holiday, field, value)
    await holiday.save()
    return holiday


@router.delete("/{id}")
async def delete_holiday(
    *,
    id: UUID,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    holiday = await Holiday.find_one(Holiday.id == id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await holiday.delete()
    return {"msg": "Holiday deleted successfully"}
