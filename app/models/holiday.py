import uuid
from datetime import date
from beanie import Document, Indexed
from pydantic import Field, UUID4

class Holiday(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    holiday_name: str
    holiday_date: Indexed(date, unique=True)

    class Settings:
        name = "holidays"
