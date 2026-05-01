import uuid
from datetime import datetime
from beanie import Document
from pydantic import Field, UUID4


class SystemSetting(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    expected_hours_per_day: int = 8
    max_daily_hours: int = 24
    weekly_submission_day: str = "friday"
    lock_week_after_approval: bool = True
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "system_settings"
