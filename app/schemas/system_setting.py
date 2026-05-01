from datetime import datetime
from pydantic import BaseModel


class SystemSettingBase(BaseModel):
    expected_hours_per_day: int = 8
    max_daily_hours: int = 24
    weekly_submission_day: str = "friday"
    lock_week_after_approval: bool = True


class SystemSettingUpdate(SystemSettingBase):
    pass


class SystemSetting(SystemSettingBase):
    updated_at: datetime
