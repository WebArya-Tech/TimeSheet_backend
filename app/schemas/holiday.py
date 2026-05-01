from datetime import date
from typing import Optional
from pydantic import BaseModel, UUID4


class HolidayBase(BaseModel):
    holiday_name: str
    holiday_date: date


class HolidayCreate(HolidayBase):
    pass


class HolidayUpdate(BaseModel):
    holiday_name: Optional[str] = None
    holiday_date: Optional[date] = None


class Holiday(HolidayBase):
    id: UUID4

    model_config = {"from_attributes": True}
