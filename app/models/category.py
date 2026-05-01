import uuid
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field, UUID4

class Category(Document):
    id: UUID4 = Field(default_factory=uuid.uuid4)
    category_name: Indexed(str, unique=True)
    allowed_on_weekend: bool = False
    allowed_on_holiday: bool = False
    is_deleted: bool = False

    class Settings:
        name = "categories"
